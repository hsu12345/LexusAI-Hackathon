from __future__ import annotations

from typing import Any

# 蓋掉常見的自動化偵測指紋（navigator.webdriver、缺少的 plugins/languages 等）。
# 這些是 Cloudflare／Akamai 等反機器人服務常見的初階檢查點；不保證能繞過進階的
# 行為分析，但能避免最容易被抓到的「一看就是 headless/自動化瀏覽器」特徵。
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-TW', 'zh', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)
    );
}
"""


def apply_stealth(context: Any) -> None:
    """對 Playwright BrowserContext 套用反偵測初始化腳本。"""
    context.add_init_script(_STEALTH_INIT_SCRIPT)


def stealth_launch_args() -> list[str]:
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
