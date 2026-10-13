ALTER TABLE "shop_products"
ADD COLUMN IF NOT EXISTS "category" VARCHAR(50) NOT NULL DEFAULT 'General';

CREATE INDEX IF NOT EXISTS "shop_products_guildId_category_idx"
ON "shop_products"("guildId", "category");
