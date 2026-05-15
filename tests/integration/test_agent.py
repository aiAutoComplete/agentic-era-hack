# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import FunctionTool

from app.agent import (
    app,
    conversion_pipeline,
    output_writer,
    root_agent,
    specialist_agents,
)


def test_cloudbridge_conversation_agent_imports() -> None:
    """The ADK app should expose a conversational root without requiring live ADC."""
    assert app.name == "app"
    assert isinstance(root_agent, LlmAgent)
    assert root_agent.name == "cloudbridge_architect"
    assert [agent.name for agent in root_agent.sub_agents] == ["conversion_pipeline"]


def test_output_writer_keeps_human_approval_tool() -> None:
    assert len(output_writer.tools) == 1
    tool = output_writer.tools[0]
    assert isinstance(tool, FunctionTool)
    assert tool.name == "write_outputs_and_generate_diagrams"
    assert tool._require_confirmation is True
    assert tool in root_agent.tools


def test_conversion_pipeline_agents_are_registered() -> None:
    assert isinstance(conversion_pipeline, SequentialAgent)
    assert [agent.name for agent in conversion_pipeline.sub_agents] == [
        "source_loader",
        "translator",
        "terraform_writer",
        "compliance_reviewer",
        "output_writer",
    ]
    names = {agent.name for agent in specialist_agents}
    assert {
        "cloudbridge_architect",
        "conversion_pipeline",
        "source_loader",
        "translator",
        "terraform_writer",
        "compliance_reviewer",
        "output_writer",
    }.issubset(names)
