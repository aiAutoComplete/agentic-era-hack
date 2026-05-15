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

from typing import Any

import pytest


@pytest.fixture
def agent_app(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Create AgentEngineApp in local test mode without ADC/network calls."""
    monkeypatch.setenv("INTEGRATION_TEST", "TRUE")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "cloudbridge-local")

    from app.agent_engine_app import agent_engine

    agent_engine.set_up()
    return agent_engine


def test_agent_engine_app_sets_up_locally(agent_app: Any) -> None:
    assert agent_app.logger is not None
    operations = agent_app.register_operations()
    assert "register_feedback" in operations.get("", [])


def test_agent_feedback(agent_app: Any) -> None:
    feedback_data = {
        "score": 5,
        "text": "Great response!",
        "user_id": "test-user-456",
        "session_id": "test-session-456",
    }

    agent_app.register_feedback(feedback_data)

    with pytest.raises(ValueError):
        agent_app.register_feedback(
            {
                "score": "invalid",
                "text": "Bad feedback",
                "user_id": "test-user-789",
                "session_id": "test-session-789",
            }
        )
