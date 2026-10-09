import asyncio

import pytest

from agno.agent import Agent
from agno.agent._tools import determine_tools_for_model
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.tools.function import Function, FunctionCall


def prepare(agent, loader, session_id):
    return determine_tools_for_model(
        agent=agent,
        model=agent.model,
        processed_tools=[loader],
        run_response=RunOutput(run_id=session_id, session_id=session_id),
        run_context=RunContext(run_id=session_id, session_id=session_id),
        session=AgentSession(session_id=session_id),
        async_mode=True,
    )


def names(tools):
    return [tool.name for tool in tools if isinstance(tool, Function)]


def test_addition_targets_originating_execution_registry():
    def late_tool():
        return "late"

    def activate(agent: Agent):
        agent.add_tool(late_tool)
        return "activated"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    first = prepare(agent, activate, "first")
    second = prepare(agent, activate, "second")

    result = FunctionCall(function=first[0], arguments={}).execute()

    assert result.status == "success"
    assert names(first) == ["activate", "late_tool"]
    assert names(second) == ["activate"]
    # add_tool still changes persistent Agent configuration for later runs.
    assert late_tool in agent.tools


def test_configuration_update_outside_tool_does_not_mutate_an_old_registry():
    def activate():
        return "activated"

    def later_configuration():
        return "later"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    old_registry = prepare(agent, activate, "first")

    agent.add_tool(later_configuration)

    assert names(old_registry) == ["activate"]
    assert later_configuration in agent.tools


@pytest.mark.parametrize("async_generator", [False, True])
async def test_lazy_tool_result_renews_context_without_leaking_to_consumer(async_generator):
    def late_tool():
        return "late"

    def consumer_tool():
        return "consumer"

    def activate(agent: Agent):
        yield "first"
        agent.add_tool(late_tool)
        yield "second"

    async def async_activate(agent: Agent):
        yield "first"
        agent.add_tool(late_tool)
        yield "second"

    loader = async_activate if async_generator else activate
    agent = Agent(model=OpenAIResponses(id="test"), tools=[loader], telemetry=False)
    originating = prepare(agent, loader, "first")
    competing = prepare(agent, loader, "second")
    call = FunctionCall(function=originating[0], arguments={})
    result = await call.aexecute()
    iterator = result.result

    if async_generator:
        assert await iterator.__anext__() == "first"
    else:
        assert next(iterator) == "first"

    agent.add_tool(consumer_tool)
    assert "consumer_tool" not in names(originating)
    assert "consumer_tool" not in names(competing)

    if async_generator:
        assert await iterator.__anext__() == "second"
        await iterator.aclose()
    else:
        assert next(iterator) == "second"
        iterator.close()

    assert "late_tool" in names(originating)
    assert "late_tool" not in names(competing)


async def test_expired_background_context_cannot_change_configuration():
    release = asyncio.Event()
    tasks = []

    def late_tool():
        return "late"

    async def activate(agent: Agent):
        async def add_after_return():
            await release.wait()
            agent.add_tool(late_tool)

        tasks.append(asyncio.create_task(add_after_return()))
        return "activated"

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    registry = prepare(agent, activate, "first")
    result = await FunctionCall(function=registry[0], arguments={}).aexecute()
    assert result.status == "success"

    release.set()
    with pytest.raises(RuntimeError, match="finished"):
        await tasks[0]

    assert late_tool not in agent.tools
    assert names(registry) == ["activate"]


@pytest.mark.parametrize("async_iterator", [False, True])
async def test_custom_lazy_iterator_registers_in_originating_run(async_iterator):
    def late_tool():
        return "late"

    class ResultIterator:
        def __init__(self, agent):
            self.agent = agent
            self.index = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.index += 1
            if self.index == 1:
                return "first"
            if self.index == 2:
                self.agent.add_tool(late_tool)
                return "second"
            raise StopIteration

    class AsyncResultIterator:
        def __init__(self, agent):
            self.result = ResultIterator(agent)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.result)
            except StopIteration:
                raise StopAsyncIteration

    def activate(agent: Agent):
        return AsyncResultIterator(agent) if async_iterator else ResultIterator(agent)

    agent = Agent(model=OpenAIResponses(id="test"), tools=[activate], telemetry=False)
    originating = prepare(agent, activate, "first")
    competing = prepare(agent, activate, "second")
    result = await FunctionCall(function=originating[0], arguments={}).aexecute()
    iterator = result.result

    if async_iterator:
        assert await iterator.__anext__() == "first"
        assert await iterator.__anext__() == "second"
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()
    else:
        assert next(iterator) == "first"
        assert next(iterator) == "second"
        with pytest.raises(StopIteration):
            next(iterator)

    assert "late_tool" in names(originating)
    assert "late_tool" not in names(competing)
