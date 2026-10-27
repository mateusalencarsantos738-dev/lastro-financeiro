"""Preserve category identity and give each existing category a stable color."""

from alembic import op
import sqlalchemy as sa

revision = "0012_category_lifecycle_color"
down_revision = "0011_future_budget_renewal"
branch_labels = None
depends_on = None

PALETTE = (
    "#326B50", "#B65F3C", "#315C96", "#8B5BA7", "#A46A19", "#217A82",
    "#A64C6E", "#566C31", "#98522D", "#4F60A9", "#8D7031", "#27836A",
    "#974F92", "#B04D4D", "#487D36", "#4574A4", "#A45D75", "#677C26",
    "#85579C", "#A86931", "#437879", "#B05C54", "#5D689A", "#82733B",
)


def upgrade():
    op.add_column("categories", sa.Column("color", sa.String(7), nullable=True))
    op.add_column("categories", sa.Column("archived_on", sa.Date(), nullable=True))
    op.add_column("categories", sa.Column("visible_until", sa.Date(), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM categories ORDER BY name, id")).all()
    for index, (category_id,) in enumerate(rows):
        if index < len(PALETTE):
            color = PALETTE[index]
        else:
            import colorsys
            hue = (index * 137.508) % 360
            r, g, b = colorsys.hls_to_rgb(hue / 360, .39, .48)
            color = f"#{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}"
        bind.execute(sa.text("UPDATE categories SET color = :color WHERE id = :id"), {"color": color, "id": category_id})
    op.alter_column("categories", "color", nullable=False)
    op.create_check_constraint("ck_category_color_hex", "categories", "color ~ '^#[0-9A-Fa-f]{6}$'")


def downgrade():
    op.drop_constraint("ck_category_color_hex", "categories", type_="check")
    op.drop_column("categories", "visible_until")
    op.drop_column("categories", "archived_on")
    op.drop_column("categories", "color")
