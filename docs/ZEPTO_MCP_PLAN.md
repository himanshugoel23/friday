# Zepto official MCP: plan (port only, NOT implemented)

Zepto publishes an official MCP server (https://mcp.zepto.co.in/mcp, OAuth per user; tools: search products, cart, order, order history). It is the right long-term source for Zepto prices (the open web hides them), so the Zepto web agent is built to be replaceable.

## The port (already in code)
`friday/shopping/sites.py`:
```
class GroceryProvider(Protocol):
    site: str
    async def search(self, req: GrocerySearch) -> GroceryResult
```
`GrocerySearch` = category, popular product names, query, pincode/area. `GroceryResult` = site, status (ok | not_visible | failed), items (`WebItem`: title, price, pack, rating, delivery time, url), sources. The site agent (A2A skill `grocery.search`), the shopping PM, the merge and the chat do not know where the numbers came from.

Swap: `ShoppingAgent(provider, overrides={"zepto": ZeptoMcpProvider(...)})` (tested with a fake in `test_an_official_mcp_provider_replaces_the_zepto_web_agent_without_changing_the_pm`). Nothing else changes.

## What the future `ZeptoMcpProvider` must do
1. Per-user OAuth: connect once from chat ("Connect Zepto" button -> OAuth page -> token stored encrypted per user, revocable, erased with "delete everything"). No token = the site stays the web agent (price not visible), never a failure.
2. Search only: call the product search tool with the popular product names, using the delivery location Zepto already knows for that user (or the saved Home/PG pincode via the location tool). Map price, pack size, rating, ETA and availability into `WebItem`; `url` = the product link the MCP returns (it counts as the cited source for the grounding rules).
3. Read-only by default. Cart/order tools are NOT used by the shopping assistant. Placing an order stays behind the existing approval + stop-at-payment rule, and Friday NEVER pays (the user pays in the Zepto app). Order history may later feed "your usual atta", only with the user's consent.
4. Fail soft: auth expired, quota or timeout -> `status="failed"` and the web agent result is used for that site.

## Open points for the founder
Zepto's MCP terms/rate limits and whether third-party agents may use it; where to keep the OAuth token (same encrypted store as other connectors); whether the OAuth redirect works from the web channel's invite link; wording for the connect step (PENDING, hear-before-change does not apply to chat text but approval does).
