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

from google.adk.workflow import Workflow

from app.agent import app, root_agent, specialist_agents


def test_cloudbridge_graph_workflow_imports() -> None:
    """The ADK app should expose the graph workflow without requiring live ADC."""
    assert app.name == "app"
    assert isinstance(root_agent, Workflow)
    assert root_agent.name == "cloudbridge_architect"
    assert root_agent.graph is not None


def test_specialist_agents_are_registered() -> None:
    names = {agent.name for agent in specialist_agents}
    assert names == {
        "project_browser_agent",
        "aws_source_analyst_agent",
        "conversion_agent",
        "terraform_generator_agent",
        "compliance_reviewer_agent",
        "human_approval_writer_agent",
    }
