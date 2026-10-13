ALTER TABLE "guild_configs"
ADD COLUMN IF NOT EXISTS "shopCategories" JSONB NOT NULL DEFAULT '[]'::jsonb;
