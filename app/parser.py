"""CloudFormation template parser for CloudBridge."""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from .models import (
    SUPPORTED_TYPES,
    MappingItem,
    ParsedResource,
    ResourceList,
    TranslationPlan,
)


def _snake(name: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    value = re.sub(r"[^0-9A-Za-z]+", "_", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower().strip("_")
    return value or "resource"


def _tf_ref(value: Any) -> str | None:
    """Return a CloudFormation reference logical id when our YAML loader flattens it."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("Ref", "Fn::Ref"):
            if key in value:
                return str(value[key])
    return None


def _string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        return str(value)
    return default


def _load_template(template_text: str) -> dict[str, Any]:
    """Load CloudFormation JSON/YAML. Unknown tags like !Ref are kept readable."""
    try:
        return json.loads(template_text)
    except json.JSONDecodeError:
        pass

    class CfnLoader(yaml.SafeLoader):
        pass

    def construct_unknown(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    CfnLoader.add_constructor(None, construct_unknown)
    try:
        loaded = yaml.load(template_text, Loader=CfnLoader)
        return loaded or {}
    except Exception as exc:
        raise ValueError(f"Template must be valid JSON or YAML: {exc}") from exc


def parse_cfn(node_input: str | dict[str, Any]) -> ResourceList:
    """Parse CloudFormation into supported and unsupported resource lists."""
    if isinstance(node_input, dict):
        template_text = (
            node_input.get("template")
            or node_input.get("message")
            or json.dumps(node_input)
        )
    else:
        template_text = node_input

    template = _load_template(template_text)
    resources = template.get("Resources", {})
    if not isinstance(resources, dict):
        raise ValueError("CloudFormation template must contain a Resources mapping.")

    supported: list[ParsedResource] = []
    unsupported: list[ParsedResource] = []
    warnings: list[str] = []

    for logical_id, body in resources.items():
        if not isinstance(body, dict):
            warnings.append(f"Skipped {logical_id}: resource body is not an object.")
            continue
        aws_type = str(body.get("Type", ""))
        properties = (
            body.get("Properties", {})
            if isinstance(body.get("Properties", {}), dict)
            else {}
        )
        item = ParsedResource(
            logical_id=str(logical_id),
            aws_type=aws_type,
            gcp_target=SUPPORTED_TYPES.get(aws_type),
            properties=properties,
        )
        if item.gcp_target:
            supported.append(item)
        else:
            unsupported.append(item)
            warnings.append(f"Unsupported for MVP: {logical_id} ({aws_type})")

    return ResourceList(resources=supported, unsupported=unsupported, warnings=warnings)


def _mapping_for_resource(resource: ParsedResource) -> MappingItem:
    gcp_type = resource.gcp_target or "unsupported"
    return MappingItem(
        aws_logical_id=resource.logical_id,
        aws_type=resource.aws_type,
        gcp_resource_type=gcp_type,
        gcp_name=_snake(resource.logical_id),
        rationale=f"{resource.aws_type} maps to {gcp_type} for the CloudBridge MVP.",
        assumptions=[
            "Generated Terraform is starter code for review, not an automatic production deployment.",
            "Region, project, naming, and CIDR choices should be verified by the migration team.",
        ],
    )


def translate_resources(parsed: ResourceList | dict[str, Any]) -> TranslationPlan:
    """Create a deterministic first-pass AWS-to-GCP architecture mapping."""
    if isinstance(parsed, dict):
        parsed = ResourceList.model_validate(parsed)

    mappings = [_mapping_for_resource(resource) for resource in parsed.resources]
    iam_bindings: list[dict[str, Any]] = []
    for resource in parsed.resources:
        if resource.aws_type in {"AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"}:
            iam_bindings.append(
                {
                    "source": resource.logical_id,
                    "member": "serviceAccount:${google_service_account.app.email}",
                    "roles": ["roles/logging.logWriter", "roles/storage.objectViewer"],
                }
            )

    return TranslationPlan(
        mappings=mappings, iam_bindings=iam_bindings, warnings=parsed.warnings
    )
