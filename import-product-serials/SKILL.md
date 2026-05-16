---
name: import-product-serials
description: "Use when importing product serial numbers, license keys, card codes, activation codes, or inventory keys into EasyStore/easystore-backend with price, quantity, cost, supplier, card type, or batch-confirmation requirements."
---

# Import Product Serials

## Overview

Import serial-number inventory into EasyStore through HTTP APIs only. Do not write serials directly to the database unless the user explicitly changes the requirement.

Use the bundled manifest-driven script:

```bash
uv run python /home/swy/.codex/skills/import-product-serials/scripts/import_product_serials.py \
  --project /home/swy/easystore-backend \
  --manifest /path/to/import_manifest.json \
  --plan-only
```

## Required Workflow

1. Gather source data: serials/license keys, product names, plans/variants, quantities, unit costs or total costs, supplier, and target EasyStore card type names.
2. Convert the data into a manifest JSON. If the source is a free-form text file or screenshot, parse it first, then create the manifest.
3. Run `--plan-only` and present the table to the user. Include supplier, card type action, quantity, unit cost, total cost, and any card types that will be created.
4. Wait for explicit user confirmation before importing.
5. Execute only with both flags:

```bash
uv run python /home/swy/.codex/skills/import-product-serials/scripts/import_product_serials.py \
  --project /home/swy/easystore-backend \
  --manifest /path/to/import_manifest.json \
  --api-base http://127.0.0.1:8021 \
  --execute --yes
```

6. Report the script's API results and verification output.

## Manifest Format

```json
{
  "supplier": {
    "name": "Supplier Name",
    "platform": "Official",
    "website": "https://example.com/",
    "notes": "optional"
  },
  "description": "Supplier import YYYY-MM-DD",
  "batches": [
    {
      "product": "Product Name",
      "plan": "1y",
      "card_type_name": "product-1y",
      "card_type_alias": "Product 一年授權",
      "create_card_type": true,
      "unit_cost": 490,
      "serials": ["AAAA-BBBB-CCCC-DDDD"]
    }
  ]
}
```

For existing card types, set `create_card_type` to `false` or omit it. For new card types, include `card_type_alias`; the script creates a `unique` card type with `is_dynamic_cost=true`.

Use `total_cost` instead of `unit_cost` only when the supplier provides a batch total. The script computes the missing value and validates `quantity * unit_cost == total_cost` within rounding tolerance.

## API Rules

- Use `GET/POST /api/v1/suppliers/` for supplier lookup/creation.
- Use `GET/POST /api/v1/card-types/` for card type lookup/creation.
- Use `POST /api/v1/cards/batch` for serial import.
- Use `Authorization: Bearer <FASTAPI_AUTH_KEY or JWT>`.
- Prefer `http://127.0.0.1:8021` when the backend is local. Storefront URLs may return HTML redirects instead of API JSON.

## Safety Checks

The script refuses to execute when:

- `--execute --yes` is missing.
- The manifest has duplicate serials in a batch or across batches.
- Quantity, unit cost, and total cost are inconsistent.
- A required card type is missing and `create_card_type` is false.
- A target serial already exists for the target card type.
- The API returns non-JSON, any batch has errors, or post-import verification fails.

Use `--show-serials` only when the user explicitly asks to display raw serials.
