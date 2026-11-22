"""Re-evaluate automatic PO state after restoring or upgrading the database."""

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.orders.lifecycle import refresh_order_lifecycle
from app.modules.orders.models import ProductionOrder


def main() -> None:
    parser = argparse.ArgumentParser(description="Đối soát trạng thái PO theo thành phẩm.")
    parser.add_argument("--apply", action="store_true", help="Lưu thay đổi kèm nhật ký.")
    args = parser.parse_args()
    changed = 0
    with SessionLocal() as db:
        order_ids = list(
            db.scalars(
                select(ProductionOrder.id)
                .where(
                    ProductionOrder.deleted_at.is_(None),
                    ProductionOrder.closed_manually.is_(False),
                    ProductionOrder.status != "cancelled",
                )
                .order_by(ProductionOrder.id)
            )
        )
        for order_id in order_ids:
            order = db.get(ProductionOrder, order_id)
            old_status = order.status
            refresh_order_lifecycle(db, order_id, actor_id=None)
            changed += order.status != old_status
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(f"{'Đã cập nhật' if args.apply else 'Chạy thử, chưa lưu'}: {changed} PO.")


if __name__ == "__main__":
    main()
