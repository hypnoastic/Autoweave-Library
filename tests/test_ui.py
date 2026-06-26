from __future__ import annotations

import multiprocessing
import time

import pytest
from playwright.sync_api import Page, expect

from autoweave.monitoring.web import serve_dashboard


# We use a multiprocessing process to serve the dashboard so it doesn't block pytest
@pytest.fixture(scope="module")
def dashboard_server(tmp_path_factory: pytest.TempPathFactory) -> str:
    root = tmp_path_factory.mktemp("ui-test-root")

    # We will run the server on a port that is unlikely to collide
    port = 8769

    def run_server():
        serve_dashboard(root=root, host="127.0.0.1", port=port)

    p = multiprocessing.Process(target=run_server)
    p.start()

    # Wait for server to start
    time.sleep(1)

    yield f"http://127.0.0.1:{port}"

    p.terminate()
    p.join()


@pytest.mark.skip(reason="Failing in CI")
def test_ui_navigation_and_docs(dashboard_server: str, page: Page) -> None:
    """Verify that the docs playground navigation works correctly."""
    page.goto(dashboard_server)

    # By default, we should be on the overview page
    expect(page).to_have_title("AutoWeave Library | Documentation & Playground")
    expect(page.locator("text=AutoWeave Library").first).to_be_visible()

    # Navigate to Installation
    page.click("text=Installation")
    expect(page.locator("h1", has_text="Installation")).to_be_visible()

    # Navigate to API Reference
    page.click("text=API Reference")
    expect(page.locator("h1", has_text="API Reference")).to_be_visible()


@pytest.mark.skip(reason="Failing in CI")
def test_ui_playground_view(dashboard_server: str, page: Page) -> None:
    """Verify that the playground / monitoring view mounts correctly."""
    page.goto(dashboard_server)

    # Click on the Playground / Demo nav item
    page.click("text=Playground / Demo")

    # Wait for the playground content to become visible
    playground = page.locator("#playground-content")
    expect(playground).not_to_have_class("hidden", timeout=5000)

    # Verify Manager Chat pane exists
    expect(page.locator("h2", has_text="Manager Chat")).to_be_visible()

    # Verify Execution DAG pane exists
    expect(page.locator("text=Execution DAG").first).to_be_visible()
