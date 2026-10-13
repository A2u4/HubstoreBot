import { textCommandCreate } from "@/lib/schemas/content";
import { collectionRoutes } from "@/lib/server/crud";
import { prepareTextCommand } from "@/lib/server/text-commands";

export const dynamic = "force-dynamic";
export const { GET, POST } = collectionRoutes({
  model: "customTextCommand", create: textCommandCreate, orderBy: { name: "asc" }, prepare: prepareTextCommand, notify: "resync",
});
