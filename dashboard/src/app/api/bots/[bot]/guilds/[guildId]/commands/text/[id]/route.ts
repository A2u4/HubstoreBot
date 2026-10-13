import { textCommandUpdate } from "@/lib/schemas/content";
import { itemRoutes } from "@/lib/server/crud";
import { prepareTextCommand } from "@/lib/server/text-commands";

export const dynamic = "force-dynamic";
export const { PATCH, DELETE } = itemRoutes({ model: "customTextCommand", update: textCommandUpdate, prepare: prepareTextCommand, notify: "resync" });
