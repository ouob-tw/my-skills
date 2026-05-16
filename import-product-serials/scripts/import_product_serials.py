#!/usr/bin/env python3
"""Import product serial inventory into EasyStore through HTTP APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


MONEY_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class SupplierSpec:
    name: str
    platform: str | None = None
    website: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class BatchSpec:
    product: str
    plan: str
    card_type_name: str
    serials: list[str]
    unit_cost: Decimal
    total_cost: Decimal
    card_type_alias: str | None = None
    create_card_type: bool = False
    description: str | None = None


@dataclass(frozen=True)
class ImportSpec:
    supplier: SupplierSpec
    description: str
    batches: list[BatchSpec]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or import product serials into EasyStore via API."
    )
    parser.add_argument("--project", default="/home/swy/easystore-backend")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:8021")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--show-serials", action="store_true")
    return parser.parse_args()


def money(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc


def load_manifest(path: Path) -> ImportSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))

    supplier_raw = raw.get("supplier")
    if isinstance(supplier_raw, str):
        supplier = SupplierSpec(name=supplier_raw)
    elif isinstance(supplier_raw, dict):
        supplier = SupplierSpec(
            name=require_str(supplier_raw, "supplier.name"),
            platform=supplier_raw.get("platform"),
            website=supplier_raw.get("website"),
            notes=supplier_raw.get("notes"),
        )
    else:
        raise ValueError("manifest supplier must be a string or object")

    description = require_str(raw, "description")
    batches_raw = raw.get("batches")
    if not isinstance(batches_raw, list) or not batches_raw:
        raise ValueError("manifest batches must be a non-empty list")

    batches = [parse_batch(item, index) for index, item in enumerate(batches_raw, 1)]
    spec = ImportSpec(supplier=supplier, description=description, batches=batches)
    validate_import_spec(spec)
    return spec


def require_str(data: dict[str, Any], field: str) -> str:
    key = field.split(".")[-1]
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def parse_batch(data: Any, index: int) -> BatchSpec:
    if not isinstance(data, dict):
        raise ValueError(f"batch {index} must be an object")

    serials = data.get("serials")
    if isinstance(serials, str):
        serial_list = [line.strip() for line in serials.splitlines() if line.strip()]
    elif isinstance(serials, list):
        serial_list = [str(item).strip() for item in serials if str(item).strip()]
    else:
        raise ValueError(f"batch {index} serials must be a list or newline string")

    if not serial_list:
        raise ValueError(f"batch {index} has no serials")

    unit_cost_raw = data.get("unit_cost")
    total_cost_raw = data.get("total_cost")
    if unit_cost_raw is None and total_cost_raw is None:
        raise ValueError(f"batch {index} requires unit_cost or total_cost")

    quantity = Decimal(len(serial_list))
    if unit_cost_raw is None:
        total_cost = money(total_cost_raw, f"batch {index} total_cost")
        unit_cost = (total_cost / quantity).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    elif total_cost_raw is None:
        unit_cost = money(unit_cost_raw, f"batch {index} unit_cost")
        total_cost = (unit_cost * quantity).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    else:
        unit_cost = money(unit_cost_raw, f"batch {index} unit_cost")
        total_cost = money(total_cost_raw, f"batch {index} total_cost")
        expected = (unit_cost * quantity).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        if expected != total_cost:
            raise ValueError(
                f"batch {index} cost mismatch: unit_cost * quantity = {expected}, "
                f"total_cost = {total_cost}"
            )

    return BatchSpec(
        product=require_str(data, f"batch {index}.product"),
        plan=require_str(data, f"batch {index}.plan"),
        card_type_name=require_str(data, f"batch {index}.card_type_name"),
        card_type_alias=data.get("card_type_alias"),
        create_card_type=bool(data.get("create_card_type", False)),
        serials=serial_list,
        unit_cost=unit_cost,
        total_cost=total_cost,
        description=data.get("description"),
    )


def validate_import_spec(spec: ImportSpec) -> None:
    seen: set[str] = set()
    for batch in spec.batches:
        local_seen: set[str] = set()
        for serial in batch.serials:
            if serial in local_seen:
                raise ValueError(f"{batch.card_type_name} contains duplicate serials")
            if serial in seen:
                raise ValueError(f"serial appears in multiple batches: {serial}")
            local_seen.add(serial)
            seen.add(serial)


def import_project_settings(project: Path) -> str:
    os.chdir(project)
    sys.path.insert(0, str(project))
    from app.core.config import settings  # type: ignore

    if not settings.fastapi_auth_key:
        raise RuntimeError("FASTAPI_AUTH_KEY is not configured")
    return settings.fastapi_auth_key


def print_plan(spec: ImportSpec, show_serials: bool) -> None:
    print(f"supplier={spec.supplier.name}")
    print(f"description={spec.description}")
    print("planned_batches:")
    for batch in spec.batches:
        action = "reuse-or-create" if batch.create_card_type else "reuse"
        print(
            f"- {batch.product} {batch.plan}: card_type={batch.card_type_name} "
            f"action={action} count={len(batch.serials)} "
            f"unit_cost={batch.unit_cost:.2f} total_cost={batch.total_cost:.2f}"
        )
        if show_serials:
            for serial in batch.serials:
                print(f"  serial={serial}")


def require_json(response: Any, context: str) -> Any:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{context} failed: HTTP {response.status_code} {response.text[:500]}"
        )
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        raise RuntimeError(
            f"{context} returned non-json: HTTP {response.status_code} "
            f"content-type={content_type}"
        )
    return response.json()


async def execute_import(args: argparse.Namespace, spec: ImportSpec) -> None:
    import httpx

    auth = import_project_settings(Path(args.project).expanduser().resolve())
    print_plan(spec, args.show_serials)

    if not (args.execute and args.yes):
        print("dry-run only; pass --execute --yes after user confirmation")
        return

    headers = {"Authorization": f"Bearer {auth}"}
    async with httpx.AsyncClient(
        base_url=args.api_base.rstrip("/"),
        headers=headers,
        timeout=30,
    ) as client:
        supplier_id = await ensure_supplier(client, spec)
        card_type_ids = await ensure_card_types(client, spec)
        await assert_no_existing_serials(client, spec, card_type_ids)
        await import_batches(client, spec, supplier_id, card_type_ids)
        await verify_import(client, spec, supplier_id, card_type_ids)


async def ensure_supplier(client: Any, spec: ImportSpec) -> int:
    suppliers = require_json(await client.get("/api/v1/suppliers/"), "GET suppliers")
    supplier = next(
        (
            item
            for item in suppliers
            if item.get("name") == spec.supplier.name and item.get("is_active", True)
        ),
        None,
    )
    if supplier:
        print(f"supplier reused id={supplier['id']}")
        return int(supplier["id"])

    created = require_json(
        await client.post(
            "/api/v1/suppliers/",
            json={
                "name": spec.supplier.name,
                "platform": spec.supplier.platform,
                "website": spec.supplier.website,
                "notes": spec.supplier.notes or spec.description,
                "is_active": True,
            },
        ),
        "POST supplier",
    )
    print(f"supplier created id={created['id']}")
    return int(created["id"])


async def ensure_card_types(client: Any, spec: ImportSpec) -> dict[str, int]:
    card_types = require_json(await client.get("/api/v1/card-types/"), "GET card-types")
    by_name = {item["name"]: item for item in card_types}
    ids: dict[str, int] = {}

    for batch in spec.batches:
        existing = by_name.get(batch.card_type_name)
        if existing:
            ids[batch.card_type_name] = int(existing["id"])
            print(f"card_type reused {batch.card_type_name} id={existing['id']}")
            continue

        if not batch.create_card_type:
            raise RuntimeError(f"required card type missing: {batch.card_type_name}")

        created = require_json(
            await client.post(
                "/api/v1/card-types/",
                json={
                    "name": batch.card_type_name,
                    "description": spec.description,
                    "type": "unique",
                    "is_limited_use": False,
                    "card_display_format": "text",
                    "password_display_format": "text",
                    "alias": batch.card_type_alias,
                    "stock_alert_threshold": 0,
                    "cost_price": None,
                    "is_dynamic_cost": True,
                    "card_prefix_display_mode": "simple",
                },
            ),
            f"POST card-type {batch.card_type_name}",
        )
        ids[batch.card_type_name] = int(created["id"])
        print(f"card_type created {batch.card_type_name} id={created['id']}")

    return ids


async def assert_no_existing_serials(
    client: Any,
    spec: ImportSpec,
    card_type_ids: dict[str, int],
) -> None:
    cards = require_json(await client.get("/api/v1/cards/"), "GET cards")
    existing = {
        (card.get("card_type_id"), card.get("card_number"))
        for card in cards
        if card.get("deleted_at") is None
    }
    collisions = [
        (batch.card_type_name, serial)
        for batch in spec.batches
        for serial in batch.serials
        if (card_type_ids[batch.card_type_name], serial) in existing
    ]
    if collisions:
        raise RuntimeError(f"target serials already exist: {len(collisions)} collision(s)")


async def import_batches(
    client: Any,
    spec: ImportSpec,
    supplier_id: int,
    card_type_ids: dict[str, int],
) -> None:
    for batch in spec.batches:
        description = batch.description or spec.description
        response = await client.post(
            "/api/v1/cards/batch",
            json={
                "card_type_id": card_type_ids[batch.card_type_name],
                "batch_cards": "\n".join(batch.serials),
                "separator": " ",
                "batch_description": description,
                "overwrite_existing": False,
                "is_priority_sale": False,
                "total_cost": float(batch.total_cost),
                "supplier_id": supplier_id,
            },
        )
        data = require_json(response, f"POST batch {batch.card_type_name}")
        print(
            f"batch {batch.card_type_name} status={response.status_code} "
            f"success={data.get('success_count')} errors={data.get('error_count')} "
            f"total={data.get('total_count')}"
        )
        if data.get("error_count"):
            raise RuntimeError(f"batch {batch.card_type_name} errors: {data.get('errors')}")


async def verify_import(
    client: Any,
    spec: ImportSpec,
    supplier_id: int,
    card_type_ids: dict[str, int],
) -> None:
    cards = require_json(await client.get("/api/v1/cards/"), "GET cards verify")
    for batch in spec.batches:
        description = batch.description or spec.description
        matches = [
            card
            for card in cards
            if card.get("card_type_id") == card_type_ids[batch.card_type_name]
            and card.get("supplier_id") == supplier_id
            and card.get("description") == description
            and card.get("card_number") in set(batch.serials)
        ]
        costs = sorted({Decimal(str(card.get("cost"))).quantize(MONEY_QUANT) for card in matches})
        statuses = sorted({card.get("status") for card in matches})
        if (
            len(matches) != len(batch.serials)
            or costs != [batch.unit_cost]
            or statuses != ["available"]
        ):
            raise RuntimeError(
                f"verification failed for {batch.card_type_name}: "
                f"count={len(matches)} costs={costs} statuses={statuses}"
            )
        print(
            f"verified {batch.card_type_name} count={len(matches)} "
            f"cost={batch.unit_cost:.2f} status=available"
        )


def main() -> None:
    args = parse_args()
    spec = load_manifest(Path(args.manifest).expanduser().resolve())
    if args.plan_only:
        print_plan(spec, args.show_serials)
        return
    asyncio.run(execute_import(args, spec))


if __name__ == "__main__":
    main()
