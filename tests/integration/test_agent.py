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

from google.adk.agents import SequentialAgent

from app.agent import app, root_agent, specialist_agents


def test_cloudbridge_pipeline_imports() -> None:
    """The ADK app should expose the simple pipeline without requiring live ADC."""
    assert app.name == "app"
    assert isinstance(root_agent, SequentialAgent)
    assert root_agent.name == "cloudbridge_architect"
    assert len(root_agent.sub_agents) == 4


def test_cloudbridge_pipeline_agents_are_registered() -> None:
    names = {agent.name for agent in specialist_agents}
    assert names == {
        "source_loader",
        "translator",
        "terraform_writer",
        "compliance_reviewer",
    }
