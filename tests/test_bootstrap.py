import asyncio

import pytest

from anyagent.configs import config
from anyagent.runtime.bootstrap import create_app

pytestmark = pytest.mark.usefixtures("runtime_paths")


def test_application_consumes_shared_config():
    app = create_app()
    assert not app.state.ready

    async def check_lifespan():
        async with app.router.lifespan_context(app):
            assert app.state.config is config
            assert app.state.data_dir == config.paths.data_dir
            assert app.state.ready
        assert not app.state.ready

    asyncio.run(check_lifespan())
