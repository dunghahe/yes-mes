"""Use lot QC in the source-of-truth PO summary, retaining legacy fallback.

Revision ID: 20261122_36
Revises: 20261122_35
"""

from alembic import op

revision: str = "20261122_36"
down_revision: str | None = "20261122_35"
branch_labels: None = None
depends_on: None = None

LEGACY_VIEW = """
        CREATE OR REPLACE VIEW v_po_summary AS
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

LOT_VIEW = """
        CREATE OR REPLACE VIEW v_po_summary AS
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
        ), qc_sx_legacy AS (
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
        ), lot_qc AS (
            SELECT lot.order_id,
                   SUM(qc.quantity_in)::bigint AS qty_in,
                   SUM(qc.ng_scrap)::bigint AS ng_scrap,
                   SUM(qc.ng_repair)::bigint AS ng_repair
            FROM lot_qc_inspections qc
            JOIN production_lots lot ON lot.id = qc.production_lot_id
            WHERE qc.deleted_at IS NULL AND lot.deleted_at IS NULL
            GROUP BY lot.order_id
        ), qc_sx AS (
            SELECT order_id, qty_in, ng_scrap, ng_repair FROM lot_qc
            UNION ALL
            SELECT old.order_id, old.qty_in, old.ng_scrap, old.ng_repair
            FROM qc_sx_legacy old
            WHERE NOT EXISTS (SELECT 1 FROM lot_qc WHERE lot_qc.order_id = old.order_id)
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


def upgrade() -> None:
    op.execute(LOT_VIEW)


def downgrade() -> None:
    op.execute(LEGACY_VIEW)
