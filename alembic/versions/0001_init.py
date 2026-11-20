"""init schema

Revision ID: 0001
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "device",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_no", sa.String(64), unique=True, index=True),
        sa.Column("brand", sa.String(64), server_default=""),
        sa.Column("model", sa.String(64), server_default=""),
        sa.Column("serial_no", sa.String(64), server_default=""),
        sa.Column("warehouse", sa.String(128), server_default=""),
        sa.Column("site", sa.String(128), server_default=""),
        sa.Column("owner", sa.String(64), server_default=""),
        sa.Column("terminal_id", sa.String(64), unique=True, index=True),
        sa.Column("phone", sa.String(16), unique=True, index=True),
        sa.Column("plate_color", sa.Integer, server_default="0"),
        sa.Column("plate", sa.String(32), server_default=""),
        sa.Column("manufacturer", sa.String(16), server_default=""),
        sa.Column("auth_code", sa.String(64), server_default=""),
        sa.Column("bound_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("unbound", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "device_state",
        sa.Column("terminal_id", sa.String(64), primary_key=True),
        sa.Column("online", sa.Boolean, server_default="false"),
        sa.Column("last_comm_at", sa.DateTime),
        sa.Column("lat", sa.Float), sa.Column("lng", sa.Float),
        sa.Column("altitude", sa.Float), sa.Column("speed", sa.Float),
        sa.Column("direction", sa.Integer),
        sa.Column("located_at", sa.DateTime),
        sa.Column("located", sa.Boolean, server_default="false"),
        sa.Column("loc_source", sa.String(16), server_default=""),
        sa.Column("external_power", sa.Boolean, server_default="true"),
        sa.Column("battery_pct", sa.Integer),
        sa.Column("ext_voltage_mv", sa.Integer),
        sa.Column("charging", sa.Boolean, server_default="false"),
        sa.Column("acc_on", sa.Boolean, server_default="false"),
        sa.Column("work_mode", sa.Integer),
        sa.Column("report_interval", sa.Integer),
        sa.Column("alarm_bits", sa.BigInteger, server_default="0"),
        sa.Column("status_bits", sa.BigInteger, server_default="0"),
        sa.Column("iccid", sa.String(24), server_default=""),
        sa.Column("imei", sa.String(24), server_default=""),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "location_record",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("terminal_id", sa.String(64), index=True),
        sa.Column("msg_serial", sa.Integer),
        sa.Column("lat", sa.Float), sa.Column("lng", sa.Float),
        sa.Column("altitude", sa.Float), sa.Column("speed", sa.Float),
        sa.Column("direction", sa.Integer),
        sa.Column("located", sa.Boolean),
        sa.Column("loc_source", sa.String(16), server_default="gnss"),
        sa.Column("alarm_bits", sa.BigInteger, server_default="0"),
        sa.Column("status_bits", sa.BigInteger, server_default="0"),
        sa.Column("battery_pct", sa.Integer),
        sa.Column("external_power", sa.Boolean, server_default="true"),
        sa.Column("collected_at", sa.DateTime, index=True),
        sa.Column("received_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("geom", geoalchemy2.Geography("POINT", srid=4326)),
        sa.UniqueConstraint("terminal_id", "msg_serial", "collected_at",
                            name="uq_loc_terminal_serial"),
    )
    op.create_index("ix_loc_terminal_time", "location_record",
                    ["terminal_id", "collected_at"])
    op.create_table(
        "alarm",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("terminal_id", sa.String(64), index=True),
        sa.Column("type", sa.String(32), index=True),
        sa.Column("level", sa.String(16), server_default="warn"),
        sa.Column("detail", sa.Text, server_default=""),
        sa.Column("triggered_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("recovered_at", sa.DateTime),
        sa.Column("acknowledged_at", sa.DateTime),
        sa.Column("ack_by", sa.String(64), server_default=""),
        sa.Column("closed_at", sa.DateTime),
        sa.Column("active", sa.Boolean, server_default="true", index=True),
    )
    op.create_table(
        "fence",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128)),
        sa.Column("site", sa.String(128), server_default=""),
        sa.Column("shape_type", sa.String(16), server_default="circle"),
        sa.Column("center_lat", sa.Float), sa.Column("center_lng", sa.Float),
        sa.Column("radius_m", sa.Float),
        sa.Column("polygon", sa.Text, server_default=""),
        sa.Column("buffer_m", sa.Float, server_default="50"),
        sa.Column("enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "fence_event",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("fence_id", sa.Integer,
                  sa.ForeignKey("fence.id"), index=True),
        sa.Column("terminal_id", sa.String(64), index=True),
        sa.Column("event", sa.String(8)),
        sa.Column("lat", sa.Float), sa.Column("lng", sa.Float),
        sa.Column("happened_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "command_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("terminal_id", sa.String(64), index=True),
        sa.Column("msg_id", sa.Integer), sa.Column("serial", sa.Integer),
        sa.Column("payload", sa.Text, server_default=""),
        sa.Column("sent_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("ack_result", sa.Integer),
        sa.Column("acked_at", sa.DateTime),
    )


def downgrade() -> None:
    for t in ("command_log", "fence_event", "fence", "alarm",
              "location_record", "device_state", "device"):
        op.drop_table(t)
