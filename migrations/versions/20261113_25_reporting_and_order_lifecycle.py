"""Add order lifecycle settings and source-of-truth report views.

Revision ID: 20261113_25
Revises: 20261113_24
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_25"
down_revision: str | None = "20261113_24"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("status", sa.String(length=20), server_default="open", nullable=False)
    )
    op.add_column(
        "orders",
        sa.Column("closed_manually", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        "ck_orders_status", "orders", "status IN ('open', 'in_progress', 'done', 'cancelled')"
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.execute("INSERT INTO settings (key, value) VALUES ('po_auto_close_pct', '100')")
    op.execute(
        """
        CREATE VIEW v_oee_pair_shift AS
        WITH production AS (
            SELECT rp.id AS daily_report_pair_id,
                   COALESCE(SUM(line.quantity_produced), 0)::bigint AS produced,
                   COALESCE(SUM(line.quantity_produced * line.cycle_time_snapshot_seconds),
                       0)::numeric AS ideal_seconds
            FROM daily_report_pairs rp
            LEFT JOIN daily_report_lines line
              ON line.daily_report_pair_id = rp.id AND line.deleted_at IS NULL
            WHERE rp.deleted_at IS NULL
            GROUP BY rp.id
        ), downtime AS (
            SELECT daily_report_pair_id, SUM(minutes)::integer AS downtime_minutes
            FROM downtime_entries WHERE deleted_at IS NULL GROUP BY daily_report_pair_id
        ), first_pass AS (
            SELECT result.daily_report_pair_id,
                   SUM(result.quantity_in)::bigint AS qc_input,
                   SUM(result.quantity_in - result.ng_scrap - result.ng_repair)::bigint AS
                       first_pass_ok
            FROM qc_pair_results result
            JOIN qc_inspections inspection ON inspection.id = result.qc_inspection_id
            WHERE result.deleted_at IS NULL AND inspection.deleted_at IS NULL
              AND inspection.pair_section_saved IS TRUE AND inspection.steps_section_saved IS TRUE
              AND (SELECT COUNT(*) FROM qc_check_steps step
                   WHERE step.qc_inspection_id = inspection.id AND step.deleted_at IS NULL) = 4
              AND (SELECT COALESCE(SUM(step.ng_scrap), 0) FROM qc_check_steps step
                   WHERE step.qc_inspection_id = inspection.id AND step.deleted_at IS NULL)
                  = (SELECT COALESCE(SUM(pair.ng_scrap), 0) FROM qc_pair_results pair
                     WHERE pair.qc_inspection_id = inspection.id AND pair.deleted_at IS NULL)
              AND (SELECT COALESCE(SUM(step.ng_repair), 0) FROM qc_check_steps step
                   WHERE step.qc_inspection_id = inspection.id AND step.deleted_at IS NULL)
                  = (SELECT COALESCE(SUM(pair.ng_repair), 0) FROM qc_pair_results pair
                     WHERE pair.qc_inspection_id = inspection.id AND pair.deleted_at IS NULL)
            GROUP BY result.daily_report_pair_id
        )
        SELECT rp.id AS daily_report_pair_id,
               report.report_date,
               rp.shift_id,
               rp.machine_pair_id,
               rp.employee_id,
               rp.downtime_recorded,
               rp.planned_minutes,
               COALESCE(down.downtime_minutes, 0) AS downtime_minutes,
               GREATEST(rp.planned_minutes - COALESCE(down.downtime_minutes, 0), 0) AS run_minutes,
               prod.produced,
               prod.ideal_seconds,
               first_pass.qc_input,
               first_pass.first_pass_ok,
               GREATEST(rp.planned_minutes - COALESCE(down.downtime_minutes, 0), 0)::numeric
                   / NULLIF(rp.planned_minutes, 0) AS availability,
               prod.ideal_seconds
                   / NULLIF(GREATEST(rp.planned_minutes - COALESCE(down.downtime_minutes, 0), 0) *
                       60, 0) AS performance,
               first_pass.first_pass_ok::numeric / NULLIF(first_pass.qc_input, 0) AS quality,
               (GREATEST(rp.planned_minutes - COALESCE(down.downtime_minutes, 0), 0)::numeric
                   / NULLIF(rp.planned_minutes, 0))
               * (prod.ideal_seconds
                   / NULLIF(GREATEST(rp.planned_minutes - COALESCE(down.downtime_minutes, 0), 0) *
                       60, 0))
               * (first_pass.first_pass_ok::numeric / NULLIF(first_pass.qc_input, 0)) AS oee
        FROM daily_report_pairs rp
        JOIN daily_reports report ON report.id = rp.daily_report_id AND report.deleted_at IS NULL
        JOIN production prod ON prod.daily_report_pair_id = rp.id
        LEFT JOIN downtime down ON down.daily_report_pair_id = rp.id
        LEFT JOIN first_pass ON first_pass.daily_report_pair_id = rp.id
        WHERE rp.deleted_at IS NULL AND report.status = 'confirmed'
        """
    )
    op.execute(
        """
        CREATE VIEW v_po_summary AS
        WITH production AS (
            SELECT schedule.order_id, SUM(line.quantity_produced)::bigint AS produced
            FROM daily_report_lines line
            JOIN daily_report_pairs rp ON rp.id = line.daily_report_pair_id AND rp.deleted_at IS
                NULL
            JOIN daily_reports report ON report.id = rp.daily_report_id AND report.deleted_at IS
                NULL
            JOIN blank_requests request ON request.id = report.blank_request_id AND
                request.deleted_at IS NULL
            JOIN schedules schedule ON schedule.id = request.schedule_id AND schedule.deleted_at IS
                NULL
            WHERE line.deleted_at IS NULL AND report.status = 'confirmed'
            GROUP BY schedule.order_id
        ), qc_sx AS (
            SELECT schedule.order_id,
                   SUM(result.quantity_in)::bigint AS qty_in,
                   SUM(result.ng_scrap)::bigint AS ng_scrap,
                   SUM(result.ng_repair)::bigint AS ng_repair
            FROM qc_pair_results result
            JOIN qc_inspections inspection ON inspection.id = result.qc_inspection_id
            JOIN daily_reports report ON report.id = inspection.daily_report_id
            JOIN blank_requests request ON request.id = report.blank_request_id
            JOIN schedules schedule ON schedule.id = request.schedule_id
            WHERE result.deleted_at IS NULL AND inspection.deleted_at IS NULL
              AND inspection.pair_section_saved IS TRUE AND inspection.steps_section_saved IS TRUE
              AND (SELECT COUNT(*) FROM qc_check_steps step
                   WHERE step.qc_inspection_id = inspection.id AND step.deleted_at IS NULL) = 4
              AND (SELECT COALESCE(SUM(step.ng_scrap), 0) FROM qc_check_steps step
                   WHERE step.qc_inspection_id = inspection.id AND step.deleted_at IS NULL)
                  = (SELECT COALESCE(SUM(pair.ng_scrap), 0) FROM qc_pair_results pair
                     WHERE pair.qc_inspection_id = inspection.id AND pair.deleted_at IS NULL)
              AND (SELECT COALESCE(SUM(step.ng_repair), 0) FROM qc_check_steps step
                   WHERE step.qc_inspection_id = inspection.id AND step.deleted_at IS NULL)
                  = (SELECT COALESCE(SUM(pair.ng_repair), 0) FROM qc_pair_results pair
                     WHERE pair.qc_inspection_id = inspection.id AND pair.deleted_at IS NULL)
              AND report.deleted_at IS NULL
              AND request.deleted_at IS NULL AND schedule.deleted_at IS NULL
            GROUP BY schedule.order_id
        ), bavia_prod AS (
            SELECT order_id, SUM(quantity_produced)::bigint AS produced
            FROM bavia_reports WHERE deleted_at IS NULL GROUP BY order_id
        ), qc_bavia AS (
            SELECT report.order_id,
                   SUM(qc.quantity_in)::bigint AS qty_in,
                   SUM(qc.ng_scrap)::bigint AS ng_scrap,
                   SUM(qc.ng_repair)::bigint AS ng_repair
            FROM bavia_qc_inspections qc
            JOIN bavia_reports report ON report.id = qc.bavia_report_id AND report.deleted_at IS
                NULL
            WHERE qc.deleted_at IS NULL GROUP BY report.order_id
        ), recheck AS (
            SELECT order_id,
                   SUM(quantity_in) FILTER (WHERE stage = 'QC')::bigint AS qc_in,
                   SUM(quantity_ok) FILTER (WHERE stage = 'QC')::bigint AS qc_ok,
                   SUM(ng_scrap) FILTER (WHERE stage = 'QC')::bigint AS qc_scrap,
                   SUM(ng_repair) FILTER (WHERE stage = 'QC')::bigint AS qc_repair,
                   SUM(quantity_in) FILTER (WHERE stage = 'QC_BAVIA')::bigint AS bavia_in,
                   SUM(quantity_ok) FILTER (WHERE stage = 'QC_BAVIA')::bigint AS bavia_ok,
                   SUM(ng_scrap) FILTER (WHERE stage = 'QC_BAVIA')::bigint AS bavia_scrap,
                   SUM(ng_repair) FILTER (WHERE stage = 'QC_BAVIA')::bigint AS bavia_repair
            FROM repair_qc_rechecks WHERE deleted_at IS NULL GROUP BY order_id
        ), repaired AS (
            SELECT order_id,
                   SUM(quantity_repaired) FILTER (WHERE stage = 'QC')::bigint AS qc_qty,
                   SUM(quantity_repaired) FILTER (WHERE stage = 'QC_BAVIA')::bigint AS bavia_qty
            FROM repair_jobs WHERE deleted_at IS NULL GROUP BY order_id
        )
        SELECT o.id AS order_id, o.po_no, o.product_id, o.process_type, o.ordered_quantity,
               o.status, o.closed_manually,
               COALESCE(prod.produced, 0) AS produced,
               COALESCE(bp.produced, 0) AS bavia_produced,
               CASE WHEN o.process_type = 'SX_ONLY'
                    THEN COALESCE(sx.qty_in, 0) - COALESCE(sx.ng_scrap, 0) - COALESCE(sx.ng_repair,
                        0) + COALESCE(r.qc_ok, 0)
                    ELSE COALESCE(bq.qty_in, 0) - COALESCE(bq.ng_scrap, 0) - COALESCE(bq.ng_repair,
                        0) + COALESCE(r.bavia_ok, 0)
               END AS finished_quantity,
               COALESCE(sx.ng_scrap, 0) + COALESCE(bq.ng_scrap, 0)
                   + COALESCE(r.qc_scrap, 0) + COALESCE(r.bavia_scrap, 0) AS ng_scrap,
               GREATEST(COALESCE(sx.ng_repair, 0) + COALESCE(r.qc_repair, 0) - COALESCE(rep.qc_qty,
                   0), 0)
                   + GREATEST(COALESCE(bq.ng_repair, 0) + COALESCE(r.bavia_repair, 0) -
                       COALESCE(rep.bavia_qty, 0), 0) AS ng_waiting_repair,
               COALESCE(rep.qc_qty, 0) + COALESCE(rep.bavia_qty, 0) AS repaired,
               GREATEST(COALESCE(rep.qc_qty, 0) - COALESCE(r.qc_in, 0), 0)
                   + GREATEST(COALESCE(rep.bavia_qty, 0) - COALESCE(r.bavia_in, 0), 0) AS
                       repaired_waiting_qc,
               CASE WHEN o.ordered_quantity > 0 THEN
                    (CASE WHEN o.process_type = 'SX_ONLY'
                          THEN COALESCE(sx.qty_in, 0) - COALESCE(sx.ng_scrap, 0) -
                              COALESCE(sx.ng_repair, 0) + COALESCE(r.qc_ok, 0)
                          ELSE COALESCE(bq.qty_in, 0) - COALESCE(bq.ng_scrap, 0) -
                              COALESCE(bq.ng_repair, 0) + COALESCE(r.bavia_ok, 0)
                     END)::numeric * 100 / o.ordered_quantity
                    ELSE 0 END AS progress_percent
        FROM orders o
        LEFT JOIN production prod ON prod.order_id = o.id
        LEFT JOIN qc_sx sx ON sx.order_id = o.id
        LEFT JOIN bavia_prod bp ON bp.order_id = o.id
        LEFT JOIN qc_bavia bq ON bq.order_id = o.id
        LEFT JOIN recheck r ON r.order_id = o.id
        LEFT JOIN repaired rep ON rep.order_id = o.id
        WHERE o.deleted_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE orders AS order_row
        SET status = CASE
            WHEN summary.finished_quantity >= CEIL(
                order_row.ordered_quantity * setting.value::numeric / 100
            ) THEN 'done'
            WHEN COALESCE(summary.produced, 0) > 0 OR COALESCE(summary.bavia_produced, 0) > 0
                THEN 'in_progress'
            ELSE 'open'
        END
        FROM v_po_summary AS summary
        CROSS JOIN settings AS setting
        WHERE order_row.id = summary.order_id
          AND setting.key = 'po_auto_close_pct'
          AND order_row.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW v_po_summary")
    op.execute("DROP VIEW v_oee_pair_shift")
    op.drop_table("settings")
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.drop_column("orders", "closed_manually")
    op.drop_column("orders", "status")
