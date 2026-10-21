"""Task engine: turns a (scenario, period) into what an agent is given.

Reads the task contract from `evbench/tasks/` and one instance from a data
tree (`evbench/scenarios/` or $TIMESAGE_DATA_ROOT), renders the question and
prompt, and builds the period-truncated sandbox. The maintainer only produces
instances; evsandbox only runs agents against what this package builds.
"""
from .prompt import episode_prompt, rephrase, task_prompt
from .question import read_instance, render_question
from .tasks import TASKS_ROOT, load_scenario, read_session_brief, task_dir
from .world import assert_no_future_leakage, build_world, refresh_world

__all__ = [
    "TASKS_ROOT", "assert_no_future_leakage", "build_world", "episode_prompt",
    "load_scenario", "read_instance", "read_session_brief", "refresh_world",
    "render_question", "rephrase", "task_dir", "task_prompt",
]
