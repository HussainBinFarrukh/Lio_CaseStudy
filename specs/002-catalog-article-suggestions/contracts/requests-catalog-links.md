# Contract: Catalog links on requests (additive)

## `POST /requests`, `PUT /requests/{id}` — `orderLines[]`

New **optional** input fields:

| Field | Type | Rule |
| --- | --- | --- |
| `catalogArticleId` | `uuid \| null` | Must be an article of the caller's organization, else **422** "Unknown catalog article". The server copies article number, description, supplier name, negotiated price and minimum quantity from the catalog (client values ignored). |
| `originalUnitPrice` | `number \| null`, ≥ 0 | The line's price before the article was applied (realised-savings basis). Ignored when `catalogArticleId` is absent. |

Server behaviour on create/update:

- Linked lines: snapshot filled from the catalog. If the line's existing link already points to
  the same article, the original snapshot is **kept** (FR: catalog changes after submission do
  not alter the request).
- Unlinked lines: the suggestion service (same rules as `POST /catalog/suggestions`, FR-021)
  stores the cheapest confirmed, comparable, cheaper alternative and `potential_saving`.
  Failures leave these fields empty; creation never fails because of them (FR-027).
- Activity: creation summary "Request created — N of M lines use catalog agreements" when
  N > 0; link changes count as order-line changes in the edit log.

## `RequestOut.order_lines[]` (snake_case) — new fields

`catalog_article_id, article_number, article_description, article_supplier_name,
negotiated_unit_price, article_min_quantity, original_unit_price,
alternative_article_number, alternative_supplier_name, alternative_unit_price,
potential_saving` (all nullable).

## `RequestOut` — new derived field

`potential_saving_total` (number | null): Σ `potential_saving` of the request's lines (FR-020).

The detail page (approval view) and the approvals list render these; buyers need no extra
endpoint.
