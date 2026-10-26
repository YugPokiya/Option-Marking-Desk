"""initial schema: chains, quotes, smile_fits, marks

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("underlying", sa.String(32), nullable=False),
        sa.Column("expiry", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("spot", sa.Float(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("div_yield", sa.Float(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chains_underlying_expiry_asof", "chains", ["underlying", "expiry", "as_of"])

    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("option_type", sa.String(1), nullable=False),
        sa.Column("bid", sa.Float()),
        sa.Column("ask", sa.Float()),
        sa.Column("last", sa.Float()),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("open_interest", sa.Integer(), nullable=False),
        sa.Column("quote_time", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("chain_id", "strike", "option_type", name="uq_quotes_chain_strike_type"),
    )
    op.create_index("ix_quotes_chain_id", "quotes", ["chain_id"])

    op.create_table(
        "smile_fits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("forward", sa.Float(), nullable=False),
        sa.Column("forward_source", sa.String(16), nullable=False),
        sa.Column("discount_factor", sa.Float(), nullable=False),
        sa.Column("t", sa.Float(), nullable=False),
        sa.Column("rmse_vol", sa.Float(), nullable=False),
        sa.Column("n_points", sa.Integer(), nullable=False),
        sa.Column("arbitrage_free", sa.Boolean(), nullable=False),
        sa.Column("min_g", sa.Float()),
        sa.Column("k_min", sa.Float(), nullable=False),
        sa.Column("k_max", sa.Float(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_smile_fits_chain_id", "smile_fits", ["chain_id"])

    op.create_table(
        "marks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fit_id", sa.Integer(), sa.ForeignKey("smile_fits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("option_type", sa.String(1), nullable=False),
        sa.Column("bid", sa.Float()),
        sa.Column("ask", sa.Float()),
        sa.Column("mid", sa.Float()),
        sa.Column("liquid", sa.Boolean(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column("market_iv", sa.Float()),
        sa.Column("model_iv", sa.Float(), nullable=False),
        sa.Column("model_price", sa.Float(), nullable=False),
        sa.Column("mark", sa.Float(), nullable=False),
        sa.Column("mark_iv", sa.Float()),
        sa.Column("lower", sa.Float(), nullable=False),
        sa.Column("upper", sa.Float(), nullable=False),
        sa.Column("method", sa.String(24), nullable=False),
    )
    op.create_index("ix_marks_fit_id", "marks", ["fit_id"])


def downgrade() -> None:
    op.drop_table("marks")
    op.drop_table("smile_fits")
    op.drop_table("quotes")
    op.drop_table("chains")
