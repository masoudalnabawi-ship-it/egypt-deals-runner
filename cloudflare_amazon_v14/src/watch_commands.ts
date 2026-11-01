import type { V14Env } from "./types";
import { resolveWatchLink } from "./watch_links";
import { saveWatch, listWatches, removeWatch } from "./watch_db";
import { sendWatchMessage } from "./telegram";

type Route = "main" | "noon";

export async function handleWatchCommand(
  env: V14Env,
  route: Route,
  message: any
): Promise<void> {
  const chatId = String(message?.chat?.id || "");
  const chatType = String(message?.chat?.type || "");
  const text = String(message?.text || "").trim();

  if (chatType !== "private" || !/^[1-9]\d*$/.test(chatId)) return;

  const [commandRaw, ...args] = text.split(/\s+/);
  const command = (commandRaw || "").split("@")[0].toLowerCase();

  if (!["/track", "/watchlist", "/untrack"].includes(command)) return;

  const reply = (text: string) => sendWatchMessage(env, route, chatId, text);
  const db = env.egypt_deals_v14_db;

  try {
    if (command === "/watchlist") {
      const items = await listWatches(db, chatId, route);

      if (!items.length) {
        await reply("📋 لا توجد منتجات في قائمة المتابعة.");
        return;
      }

      const lines = items.map(item => {
        const targets = [
          item.target_price !== null ? `السعر ≤ ${item.target_price} جنيه` : "",
          item.target_discount !== null ? `الخصم ≥ ${item.target_discount}%` : ""
        ].filter(Boolean).join(" أو ");

        return `#${item.id} | ${item.store.toUpperCase()}\n${targets}\n${item.product_url}`;
      });

      await reply(`📋 منتجاتك المتابعة:\n\n${lines.join("\n\n")}`.slice(0, 4096));
      return;
    }

    if (command === "/untrack") {
      const id = Number(args[0]);

      if (!Number.isSafeInteger(id) || id <= 0) {
        await reply("استخدم: /untrack 123");
        return;
      }

      const removed = await removeWatch(db, chatId, route, id);
      await reply(removed ? "✅ تم إلغاء متابعة المنتج." : "المنتج غير موجود في قائمتك.");
      return;
    }

    // /track <URL> price=500 discount=30
    const url = args[0] || "";
    const priceArg = args.find(x => /^price=/i.test(x));
    const discountArg = args.find(x => /^discount=/i.test(x));

    if (!url || (!priceArg && !discountArg)) {
      await reply("استخدم:\n/track رابط_المنتج price=500\nأو\n/track رابط_المنتج discount=30\nويمكن استخدام الشرطين معًا.");
      return;
    }

    const price = priceArg ? Number(priceArg.split("=")[1]) : null;
    const discount = discountArg ? Number(discountArg.split("=")[1]) : null;

    const product = await resolveWatchLink(url);

    await saveWatch(db, {
      chatId,
      botRoute: route,
      store: product.store,
      productUrl: product.url,
      externalId: product.externalId,
      targetPrice: price,
      targetDiscount: discount
    });

    await reply(`✅ تمت إضافة المنتج للمتابعة.\nالمتجر: ${product.store}\nالمنتج: ${product.externalId}\n\nاستخدم /watchlist لعرض القائمة.`);
  } catch (error) {
    console.error("watch_command_error", error);
    await reply("❌ تعذر تنفيذ الأمر. تأكد من صحة الرابط وقيمة السعر أو الخصم.");
  }
}
