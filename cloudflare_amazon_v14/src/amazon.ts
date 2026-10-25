import type { DealCandidate, Surface } from "./types";
import { cleanText, decodeEntities, extractBalancedObject, isProtectedPage, parseNumber, stripTags } from "./util";

const BASE = "https://www.amazon.eg";

const q = (name: string, category: string, query: string, priority = 1): Surface => ({
  name, category, priority, url: `${BASE}/s?k=${encodeURIComponent(query)}`,
});
const d = (name: string, percent: number, priority = 1): Surface => ({
  name, category: "global", priority, url: `${BASE}/s?k=${encodeURIComponent("deals")}&rh=p_8%3A${percent}-`,
});

/*
 * Amazon percentage filter + category/query.
 *
 * This is stronger than simply searching for text such as
 * "80% off" because Amazon itself is asked to apply its
 * discount filter to the result set.
 */
const pf = (
  name: string,
  category: string,
  query: string,
  percent: number,
  priority = 1,
): Surface => ({
  name,
  category,
  priority,
  url:
    `${BASE}/s?k=${encodeURIComponent(query)}` +
    `&rh=p_8%3A${percent}-`,
});

export const AMAZON_SURFACES: Surface[] = [
  /* V14_ULTRA65_COMPREHENSIVE_20261025: supplementary category-wide 65% discovery leads; not proof of a real discount. */
  pf("ultra65_full_phone_cases","mobiles","phone case",65,3.25),
  pf("ultra65_full_screen_protectors","mobiles","screen protector",65,3.25),
  pf("ultra65_full_chargers","mobiles","fast charger",65,3.25),
  pf("ultra65_full_power_banks","mobiles","power bank",65,3.25),
  pf("ultra65_full_tablet_accessories","computers","tablet accessories",65,3.25),
  pf("ultra65_full_ssd_storage","computers","external SSD",65,3.25),
  pf("ultra65_full_memory_cards","electronics","memory card",65,3.25),
  pf("ultra65_full_routers","electronics","wifi router",65,3.25),
  pf("ultra65_full_gaming_accessories","electronics","gaming accessories",65,3.25),
  pf("ultra65_full_security_cameras","electronics","security camera",65,3.25),
  pf("ultra65_full_smart_plugs","electronics","smart plug",65,3.25),
  pf("ultra65_full_cookware","kitchen","cookware set",65,3.25),
  pf("ultra65_full_bakeware","kitchen","baking trays",65,3.25),
  pf("ultra65_full_food_storage","kitchen","food storage containers",65,3.25),
  pf("ultra65_full_bedding","home","bedding sets",65,3.25),
  pf("ultra65_full_bathroom","home","bathroom accessories",65,3.25),
  pf("ultra65_full_furniture","home","furniture",65,3.25),
  pf("ultra65_full_home_lighting","home","lighting fixtures",65,3.25),
  pf("ultra65_full_power_tools","tools","power tools",65,3.25),
  pf("ultra65_full_hand_tools","tools","hand tools",65,3.25),
  pf("ultra65_full_haircare","beauty","hair care",65,3.25),
  pf("ultra65_full_fragrance","beauty","perfume",65,3.25),
  pf("ultra65_full_makeup","beauty","makeup",65,3.25),
  pf("ultra65_full_shaving","personal_care","shaving accessories",65,3.25),
  pf("ultra65_full_mens_clothing","fashion","men clothing",65,3.25),
  pf("ultra65_full_womens_clothing","fashion","women clothing",65,3.25),
  pf("ultra65_full_kids_clothing","fashion","kids clothing",65,3.25),
  pf("ultra65_full_watches","fashion","watches",65,3.25),
  pf("ultra65_full_luggage","fashion","luggage",65,3.25),
  pf("ultra65_full_board_games","toys","board games",65,3.25),
  pf("ultra65_full_baby_care","baby","baby care",65,3.25),
  pf("ultra65_full_baby_diapers","baby","diapers",65,3.25),
  pf("ultra65_full_camping","sports","camping equipment",65,3.25),
  pf("ultra65_full_cycling","sports","cycling accessories",65,3.25),
  pf("ultra65_full_car_care","automotive","car cleaning",65,3.25),
  pf("ultra65_full_car_electronics","automotive","car electronics",65,3.25),
  pf("ultra65_full_coffee_tea","grocery","coffee tea",65,3.25),
  pf("ultra65_full_snacks","grocery","snacks",65,3.25),
  pf("ultra65_full_laundry","grocery","laundry detergent",65,3.25),
  pf("ultra65_full_household_cleaners","home","household cleaning",65,3.25),
  pf("ultra65_full_office_supplies","office","office supplies",65,3.25),
  pf("ultra65_full_printers","office","printer accessories",65,3.25),
  pf("ultra65_full_pet_food","pets","pet food",65,3.25),
  pf("ultra65_full_musical_accessories","music","musical instrument accessories",65,3.25),

  /* V14_ULTRA65_KEYWORD_EXPANSION_2026 */
  pf("ultra65_kw_phone_accessories","mobiles","phone accessories",65,3.1),
  pf("ultra65_kw_usb_c_cables","mobiles","USB C cable",65,3.1),
  pf("ultra65_kw_phone_holders","mobiles","phone holder",65,3.1),
  pf("ultra65_kw_kitchen_gadgets","kitchen","kitchen gadgets",65,3.1),
  pf("ultra65_kw_storage_organizers","home","storage organizer",65,3.1),
  pf("ultra65_kw_air_fryer_accessories","kitchen","air fryer accessories",65,3.1),
  pf("ultra65_kw_hair_trimmers","personal_care","hair trimmer",65,3.1),
  pf("ultra65_kw_electric_toothbrush","personal_care","electric toothbrush",65,3.1),
  pf("ultra65_kw_skin_care","beauty","skin care",65,3.1),
  pf("ultra65_kw_mens_shoes","fashion","men shoes",65,3.1),
  pf("ultra65_kw_womens_bags","fashion","women bags",65,3.1),
  pf("ultra65_kw_sportswear","fashion","sportswear",65,3.1),
  pf("ultra65_kw_building_blocks","toys","building blocks",65,3.1),
  pf("ultra65_kw_remote_control_cars","toys","remote control car",65,3.1),
  pf("ultra65_kw_educational_toys","toys","educational toys",65,3.1),
  pf("ultra65_kw_wireless_earbuds","electronics","wireless earbuds",65,3.1),
  pf("ultra65_kw_smart_watches","electronics","smart watch",65,3.1),
  pf("ultra65_kw_bluetooth_speakers","electronics","bluetooth speaker",65,3.1),
  pf("ultra65_kw_led_lights","home","LED light",65,3.1),
  pf("ultra65_kw_extension_cords","home","extension cord",65,3.1),
  pf("ultra65_kw_cleaning_tools","home","cleaning tools",65,3.1),
  pf("ultra65_kw_fitness_accessories","sports","fitness accessories",65,3.1),
  pf("ultra65_kw_yoga_mats","sports","yoga mat",65,3.1),
  pf("ultra65_kw_resistance_bands","sports","resistance bands",65,3.1),
  pf("ultra65_kw_car_accessories","automotive","car accessories",65,3.1),
  pf("ultra65_kw_car_organizers","automotive","car organizer",65,3.1),
  pf("ultra65_kw_car_phone_holders","automotive","car phone holder",65,3.1),
  pf("ultra65_kw_laptop_stands","computers","laptop stand",65,3.1),
  pf("ultra65_kw_computer_mice","computers","computer mouse",65,3.1),
  pf("ultra65_kw_usb_hubs","computers","USB hub",65,3.1),
  pf("ultra65_kw_vacuum_cleaners","appliances","vacuum cleaner",65,3.1),
  pf("ultra65_kw_coffee_makers","appliances","coffee maker",65,3.1),
  pf("ultra65_kw_blenders","appliances","blender",65,3.1),
  pf("ultra65_kw_pet_toys","pets","pet toys",65,3.1),
  pf("ultra65_kw_pet_grooming","pets","pet grooming",65,3.1),
  pf("ultra65_kw_pet_accessories","pets","pet accessories",65,3.1),
  /* V14_ULTRA_ALL_70_99_V1: 70%+ category-wide Amazon discount radar. */
  pf("ultra70_electronics","electronics","electronics",70,4.8),
  pf("ultra70_computers","computers","computer accessories",70,4.8),
  pf("ultra70_appliances","appliances","home appliances",70,4.8),
  pf("ultra70_mobiles","mobiles","mobile phones",70,4.8),
  pf("ultra70_home","home","home products",70,4.8),
  pf("ultra70_kitchen","kitchen","kitchen appliances",70,4.8),
  pf("ultra70_beauty","beauty","beauty",70,4.8),
  pf("ultra70_fashion","fashion","fashion",70,4.8),
  pf("ultra70_sports","sports","sports fitness",70,4.8),
  pf("ultra70_baby","baby","baby products",70,4.8),
  pf("ultra70_grocery","grocery","grocery",70,4.8),
  pf("ultra70_pets","pets","pet supplies",70,4.8),
  pf("ultra70_office","office","office products",70,4.8),
  pf("ultra70_automotive","automotive","automotive accessories",70,4.8),
  pf("ultra70_toys","toys","toys",70,4.8),
  pf("ultra70_health","health","health personal care",70,4.8),
  pf("ultra70_tools","tools","tools home improvement",70,4.8),
  pf("ultra70_music","music","musical instruments",70,4.8),
  pf("ultra70_air_conditioners","appliances","air conditioners",70,5.0),
  pf("ultra70_televisions","electronics","televisions",70,5.0),
  pf("ultra70_refrigerators","appliances","refrigerators",70,5.0),
  pf("ultra70_washing_machines","appliances","washing machines",70,5.0),
  pf("ultra70_laptops","computers","laptops",70,5.0),
  pf("ultra70_perfumes","beauty","perfumes",70,5.0),
  pf("ultra70_supermarket","grocery","supermarket",70,5.0),
  pf("ultra70_snacks","grocery","snacks",70,5.0),

  { name: "goldbox", category: "global", url: `${BASE}/gp/goldbox/`, priority: 3.5 },
  q("limited_time","global","limited time deals",1.8), q("clearance","global","clearance deals",1.5),
  q("90off","global","90% off deals",2.2), q("75off","global","75% off deals",2.1),
  q("70off","global","70% off deals",2.0), q("65off","global","65% off deals",2.0), q("50off","global","50% off deals",1.0),
  d("70flashfilter",70,5.2),
  d("65filter",65,2.6), d("70filter",70,2.7), d("75filter",75,2.9), d("90filter",90,3.0), d("50filter",50,1.0),

  /*
   * AMAZON_ULTRA_V4_EXCEPTIONAL_80
   *
   * Dedicated radar for exceptional discounts.
   * Discovery is only a lead:
   * rendered product-page proof is still mandatory.
   */
  q("95off","global","95% off deals",4.5),
  q("85off","global","85% off deals",4.2),
  q("80off","global","80% off deals",4.0),

  d("80filter",80,4.2),
  d("85filter",85,4.4),
  d("95filter",95,4.7),

  pf("electronics_80filter","electronics","electronics",80,3.8),
  pf("tvs_80filter","electronics","televisions",80,4.0),
  pf("gaming_80filter","electronics","gaming",80,3.6),
  pf("smart_home_80filter","electronics","smart home",80,3.6),
  pf("computer_accessories_80filter","computers","computer accessories",80,3.8),

  pf("appliances_80filter","appliances","home appliances",80,3.8),
  pf("home_80filter","home","home",80,3.5),

  pf("beauty_80filter","beauty","beauty",80,4.0),
  pf("personal_care_80filter","beauty","personal care",80,4.2),

  pf("automotive_80filter","automotive","automotive accessories",80,4.2),

  pf("shoes_80filter","fashion","shoes",80,3.5),

  pf("sports_80filter","sports","sports fitness",80,3.4),

  pf("baby_80filter","baby","baby products",80,3.5),

  pf("grocery_80filter","grocery","grocery",80,3.7),
  pf("snacks_80filter","grocery","snacks",80,4.0),
  pf("chocolate_80filter","grocery","chocolate",80,3.9),

  pf("pet_food_80filter","pets","pet food",80,4.1),

  pf("office_80filter","office","office products",80,3.4),

  q("electronics_65hot","electronics","electronics 65% off",1.8), q("appliances_65hot","appliances","home appliances 65% off",1.8),
  q("beauty_65hot","beauty","beauty 65% off",1.6), q("fashion_65hot","fashion","fashion 65% off",1.5),
  q("mobiles_65hot","mobiles","mobile phones 65% off",2.0), q("laptops_65hot","computers","laptops 65% off",2.0),
  q("tablets_65hot","computers","tablets 65% off",1.9), q("tvs_65hot","electronics","televisions 65% off",2.0),
  q("audio_65hot","electronics","headphones earbuds speakers 65% off",1.9), q("gaming_65hot","electronics","gaming video games 65% off",1.9),
  q("cameras_65hot","electronics","cameras photography 65% off",1.8), q("networking_65hot","electronics","routers networking 65% off",1.8),
  q("smart_home_65hot","electronics","smart home devices 65% off",1.8), q("kitchen_65hot","kitchen","kitchen appliances 65% off",2.0),
  q("home_65hot","home","home products 65% off",1.9), q("furniture_65hot","home","furniture 65% off",1.8),
  q("tools_65hot","tools","tools home improvement 65% off",1.9), q("cleaning_65hot","home","cleaning products 65% off",1.7),
  q("personal_care_65hot","beauty","personal care 65% off",1.9), q("health_65hot","health","health personal care 65% off",1.8),
  q("perfumes_65hot","beauty","perfumes fragrances 65% off",1.9), q("shoes_65hot","fashion","shoes 65% off",1.8),
  q("bags_65hot","fashion","bags luggage 65% off",1.8), q("watches_65hot","fashion","watches 65% off",1.8),
  q("jewelry_65hot","fashion","jewelry 65% off",1.7), q("sports_65hot","sports","sports fitness 65% off",1.9),
  q("outdoor_65hot","sports","outdoor camping 65% off",1.8), q("toys_65hot","toys","toys games 65% off",1.9),
  q("baby_65hot","baby","baby products 65% off",1.9), q("grocery_65hot","grocery","grocery food beverages 65% off",1.7),
  q("pet_65hot","pets","pet supplies 65% off",1.8), q("office_65hot","office","office products 65% off",1.8),
  q("printers_65hot","office","printers scanners 65% off",1.7), q("books_65hot","books","books 65% off",1.6),
  q("automotive_65hot","automotive","automotive accessories 65% off",1.8), q("music_65hot","music","musical instruments 65% off",1.7),
  q("mobiles","mobiles","mobile phones deals",1.3), q("mobile_accessories","mobiles","mobile accessories deals"),
  q("laptops","computers","laptops deals",1.3), q("computer_accessories","computers","computer accessories deals"),
  q("tablets","computers","tablets deals"), q("tvs","electronics","smart tv deals",1.2), q("audio","electronics","headphones earbuds speakers deals"),
  q("gaming","electronics","gaming deals"), q("cameras","electronics","camera deals"), q("appliances","appliances","home appliances deals",1.3),
  q("refrigerators","appliances","refrigerator deals"), q("washers","appliances","washing machine deals"), q("ac","appliances","air conditioner deals"),
  q("kitchen","kitchen","kitchen appliances deals",1.2), q("cookware","kitchen","cookware kitchen deals"), q("home","home","home deals"),
  q("furniture","home","furniture deals"), q("tools","tools","tools home improvement deals"), q("beauty","beauty","beauty deals"),
  q("personal_care","beauty","personal care deals"), q("men_fashion","fashion","men fashion deals"), q("women_fashion","fashion","women fashion deals"),
  q("kids_fashion","fashion","kids clothing deals"), q("shoes","fashion","shoes deals"), q("bags","fashion","bags deals"),
  q("watches","fashion","watches deals"), q("sports","sports","sports fitness deals"), q("toys","toys","toys games deals"),
  q("baby","baby","baby products deals"), q("grocery","grocery","grocery food deals"), q("coffee","grocery","coffee tea deals"),
  q("cleaning","grocery","detergent cleaning products deals"), q("automotive","automotive","car accessories deals"), q("office","office","office supplies deals"),
  q("luggage","fashion","luggage travel accessories deals"), q("jewelry","fashion","jewelry deals"), q("health","health","health personal care deals"),
  q("perfumes","beauty","perfumes fragrances deals"), q("musical_instruments","music","musical instruments deals"),
  q("printers","office","printers scanners deals"), q("networking","electronics","routers networking deals"), q("smart_home","electronics","smart home devices deals"),

  /*
   * ========================================================
   * V14 FULL AMAZON EGYPT COVERAGE
   * ========================================================
   *
   * Supermarket / grocery / daily essentials are deliberately
   * split into smaller surfaces so one generic search cannot
   * hide strong deals deeper in Amazon search results.
   */

  q("supermarket","grocery","supermarket deals",1.35),
  q("pantry","grocery","pantry food deals",1.20),
  q("snacks","grocery","snacks deals",1.20),
  q("chocolate","grocery","chocolate candy deals",1.15),
  q("biscuits","grocery","biscuits cookies deals",1.15),
  q("breakfast","grocery","breakfast cereal deals",1.10),
  q("rice_pasta","grocery","rice pasta noodles deals",1.15),
  q("canned_food","grocery","canned food deals",1.05),
  q("sauces","grocery","sauces condiments deals",1.05),
  q("spices","grocery","spices seasoning deals",1.05),
  q("oils_ghee","grocery","cooking oil ghee deals",1.10),
  q("baking","grocery","baking ingredients deals",1.00),

  q("beverages","grocery","beverages drinks deals",1.25),
  q("water","grocery","mineral water deals",1.10),
  q("juices","grocery","juice drinks deals",1.10),
  q("soft_drinks","grocery","soft drinks deals",1.10),
  q("energy_drinks","grocery","energy drinks deals",1.00),
  q("tea","grocery","tea deals",1.10),

  /*
   * Household daily-use supermarket products.
   */
  q("household_essentials","home","household essentials deals",1.30),
  q("laundry","home","laundry detergent deals",1.25),
  q("dishwashing","home","dishwashing detergent deals",1.20),
  q("paper_tissues","home","tissues toilet paper kitchen rolls deals",1.20),
  q("trash_bags","home","trash garbage bags deals",1.00),
  q("air_fresheners","home","air freshener deals",1.00),

  /*
   * Personal care.
   */
  q("skincare","beauty","skin care deals",1.20),
  q("haircare","beauty","hair care shampoo conditioner deals",1.20),
  q("oral_care","health","toothpaste toothbrush oral care deals",1.15),
  q("deodorants","beauty","deodorant deals",1.05),
  q("shaving","beauty","shaving grooming deals",1.10),

  /*
   * Home departments.
   */
  q("storage","home","storage organization deals",1.15),
  q("bedding","home","bedding sheets pillows deals",1.10),
  q("bath","home","bathroom accessories deals",1.00),
  q("lighting","home","lighting lamps deals",1.10),
  q("garden","home","garden gardening deals",1.00),
  q("electrical","tools","electrical tools supplies deals",1.05),
  q("plumbing","tools","plumbing supplies deals",1.00),
  q("hardware","tools","hardware tools deals",1.10),

  /*
   * Office / education / creative.
   */
  q("stationery","office","stationery deals",1.10),
  q("school_supplies","office","school supplies deals",1.10),
  q("arts_crafts","office","arts crafts deals",1.00),

  /*
   * Sports / transport.
   */
  q("fitness","sports","fitness equipment deals",1.15),
  q("cycling","sports","cycling bicycle accessories deals",1.05),
  q("car_care","automotive","car care products deals",1.10),

  /*
   * Pet consumables deserve their own rotation.
   */
  q("pet_food","pets","pet food deals",1.15),

  /*
   * Dedicated ≥65% discovery leads.
   * These remain LEADS only: Playwright must still prove
   * the live Amazon product-page discount before Ultra.
   */
  q("supermarket_65hot","grocery","supermarket grocery 65% off",1.90),
  q("food_beverage_65hot","grocery","food beverages 65% off",1.80),
  q("snacks_65hot","grocery","snacks chocolate 65% off",1.70),
  q("coffee_tea_65hot","grocery","coffee tea 65% off",1.70),
  q("household_essentials_65hot","home","household essentials 65% off",1.90),
  q("laundry_65hot","home","laundry cleaning 65% off",1.70),
  q("skincare_65hot","beauty","skin care 65% off",1.80),
  q("haircare_65hot","beauty","hair care 65% off",1.80),
  q("oral_care_65hot","health","oral care 65% off",1.70),
  q("storage_65hot","home","storage organization 65% off",1.70),
  q("bedding_65hot","home","bedding home textile 65% off",1.70),
  q("lighting_65hot","home","lighting lamps 65% off",1.70),
  q("garden_65hot","home","garden products 65% off",1.60),
  q("stationery_65hot","office","stationery office supplies 65% off",1.70),
  q("fitness_65hot","sports","fitness equipment 65% off",1.80),
  q("cycling_65hot","sports","cycling accessories 65% off",1.60),
  q("car_care_65hot","automotive","car care 65% off",1.70),
  q("pet_food_65hot","pets","pet food 65% off",1.60),
];

function attr(tag: string, name: string): string {
  const m = tag.match(new RegExp(`${name}=["']([^"']*)["']`, "i"));
  return m ? decodeEntities(m[1]) : "";
}

function extractTextAround(card: string, regex: RegExp): string {
  const m = card.match(regex);
  return m ? stripTags(m[1]) : "";
}

function parseGoldbox(html: string, surface: Surface): DealCandidate[] {
  const marker = '"productSearchResponse":';
  const products: Record<string, any>[] = [];
  let pos = 0;
  while (true) {
    const idx = html.indexOf(marker, pos);
    if (idx < 0) break;
    const start = html.indexOf("{", idx + marker.length);
    if (start < 0) break;
    const raw = extractBalancedObject(html, start);
    if (!raw) { pos = idx + marker.length; continue; }
    try {
      const payload = JSON.parse(raw);
      if (Array.isArray(payload?.products)) products.push(...payload.products);
    } catch {}
    pos = start + raw.length;
  }
  const unique = new Map<string, DealCandidate>();
  for (const p of products) {
    const asin = String(p?.asin || "").trim().toUpperCase();
    if (!/^[A-Z0-9]{10}$/.test(asin)) continue;
    const title = cleanText(p?.title || asin);
    const price = p?.price && typeof p.price === "object" ? p.price : {};
    // Amazon-specific parsing for consistent Arabic/English price handling.
    const current = parseAmazonPrice(String(price?.priceToPay?.price ?? ""));
    let old = parseAmazonPrice(String(price?.basisPrice?.price ?? ""));
    if (!(current > 0)) continue;
    if (!(old > current)) old = 0;
    const link = String(p?.link || `/dp/${asin}`).split("?")[0];
    const url = link.startsWith("http") ? link : BASE + (link.startsWith("/") ? link : `/${link}`);
    let image = "";
    const imageData = p?.image;
    if (imageData && typeof imageData === "object") {
      const chosen = typeof imageData.hiRes === "object" ? imageData.hiRes : typeof imageData.lowRes === "object" ? imageData.lowRes : {};
      const baseUrl = String(chosen?.baseUrl || "");
      const ext = String(chosen?.extension || "");
      image = baseUrl ? (ext && !baseUrl.endsWith(`.${ext}`) ? `${baseUrl}.${ext}` : baseUrl) : "";
    }
    const dealDetails = p?.dealDetails && typeof p.dealDetails === "object" ? p.dealDetails : {};
    const addToCart = p?.addToCart && typeof p.addToCart === "object" ? p.addToCart : {};
    const promoBlob = JSON.stringify({ dealBadge: p?.dealBadge, messaging: p?.messaging });
    const low = promoBlob.toLowerCase();
    const flash = Boolean(addToCart?.isLightningDeal || low.includes("limited") || promoBlob.includes("لفترة محدودة") || promoBlob.includes("عرض محدود"));
    const couponHint = ["coupon","voucher","كوبون","قسيمة"].some(t => low.includes(t));
    const promoHint = couponHint ? "coupon" : flash ? "limited_time" : Object.keys(dealDetails).length ? "amazon_deal" : "";
    const deal: DealCandidate = {
      store: "amazon", external_id: asin, title, url, current_price: current, old_price: old || null,
      image_url: image, category: surface.category, source: surface.name,
      metadata: { goldbox: true, promo_hint: promoHint, coupon_hint: couponHint, flash_hint: flash,
        deal_id: dealDetails?.id, deal_type: dealDetails?.type, deal_state: dealDetails?.state },
    };
    const prev = unique.get(asin);
    const pct = old > current ? ((old-current)/old)*100 : 0;
    const prevPct = prev?.old_price && prev.old_price > prev.current_price ? ((prev.old_price-prev.current_price)/prev.old_price)*100 : -1;
    if (!prev || pct > prevPct) unique.set(asin, deal);
  }
  return [...unique.values()];
}

// Amazon-only price parsing: avoid changing Noon or shared utility semantics.
// Reject ambiguous/malformed values rather than manufacturing a discount.
function parseAmazonPrice(raw: string): number {
  // Amazon-only parser. Never infer prices from arbitrary numeric substrings.
  const value = stripTags(raw)
    .replace(/[٠-٩]/g, d => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/٫/g, ".")
    .replace(/٬/g, ",")
    .replace(/[\u200e\u200f\u061c\u00a0\u202f]/g, " ")
    .trim();

  // Accept only known Egyptian currency markers surrounding one price.
  const token = value
    .replace(/^(?:EGP|LE|E\.G\.P\.|ج\.?\s*م\.?|جنيه(?:اً|ا|ات)?(?:\s+مصري(?:ة)?)?)\s*/i, "")
    .replace(/\s*(?:EGP|LE|E\.G\.P\.|ج\.?\s*م\.?|جنيه(?:اً|ا|ات)?(?:\s+مصري(?:ة)?)?)$/i, "")
    .trim();

  if (!/^\d[\d.,]*$/.test(token)) return 0;

  let normalized = "";

  if (/^\d+$/.test(token)) {
    normalized = token;
  } else if (/^\d+\.\d{1,2}$/.test(token)) {
    normalized = token;
  } else if (/^\d{1,3}(?:,\d{3})+$/.test(token)) {
    normalized = token.replace(/,/g, "");
  } else if (/^\d{1,3}(?:,\d{3})+\.\d{1,2}$/.test(token)) {
    normalized = token.replace(/,/g, "");
  } else if (/^\d{1,3}(?:\.\d{3})+,\d{1,2}$/.test(token)) {
    normalized = token.replace(/\./g, "").replace(",", ".");
  } else {
    // Reject single-dot three-digit ambiguity, malformed grouping,
    // comma decimals, and any unrecognized numeric layout.
    return 0;
  }

  const price = Number(normalized);
  return Number.isFinite(price) && price > 0 && price <= 1_000_000_000
    ? price
    : 0;
}

function parseSearch(html: string, surface: Surface): DealCandidate[] {
  const starts: Array<{index: number; asin: string}> = [];
  const tagRe = /<div\b[^>]*\bdata-component-type=["']s-search-result["'][^>]*>/gi;
  let m: RegExpExecArray | null;
  while ((m = tagRe.exec(html)) !== null && starts.length < 80) {
    const asin = m[0].match(/\bdata-asin=["']([A-Z0-9]{10})["']/i)?.[1];
    if (asin) starts.push({ index: m.index, asin: asin.toUpperCase() });
  }
  const unique = new Map<string, DealCandidate>();
  for (let i = 0; i < starts.length; i++) {
    const start = starts[i];
    const end = i + 1 < starts.length ? starts[i + 1].index : Math.min(html.length, start.index + 120000);
    const card = html.slice(start.index, end);
    const title = extractTextAround(card, /<h2\b[^>]*>[\s\S]{0,3000}?<span\b[^>]*>([\s\S]{0,2000}?)<\/span>/i)
      || extractTextAround(card, /<h2\b[^>]*>([\s\S]{0,2500}?)<\/h2>/i);
    const currentMatch = card.match(/<span\b[^>]*class=["'][^"']*\ba-price\b[^"']*["'][^>]*>[\s\S]{0,1000}?<span\b[^>]*class=["'][^"']*\ba-offscreen\b[^"']*["'][^>]*>([\s\S]{0,250}?)<\/span>/i);
    const current = parseAmazonPrice(currentMatch ? currentMatch[1] : "");
    if (!title || !(current > 0)) continue;
    let old = 0;
    const oldRegion = card.match(/<span\b[^>]*class=["'][^"']*\ba-text-price\b[^"']*["'][^>]*>([\s\S]{0,1600}?)<\/span>/i);
    if (oldRegion) old = parseAmazonPrice(oldRegion[1]);
    // V14_AMAZON_STRICT_DISCOUNT_EVIDENCE:
    // Never manufacture an old price from a discount badge.
    // Only explicitly extracted card prices may become price evidence.
    // Product-page verification remains mandatory before delivery.
    if (!(old > current)) old = 0;
    const imgTag = card.match(/<img\b[^>]*(?:class=["'][^"']*s-image[^"']*["'])[^>]*>/i)?.[0] || card.match(/<img\b[^>]*>/i)?.[0] || "";
    const image = attr(imgTag, "src") || attr(imgTag, "data-src");
    const text = stripTags(card.slice(0, 12000));
    const low = text.toLowerCase();
    const promoMarker = ["coupon","كوبون","خصم إضافي","limited time deal","عرض لفترة محدودة"].find(x => low.includes(x.toLowerCase())) || "";
    const deal: DealCandidate = {
      store: "amazon", external_id: start.asin, title, url: `${BASE}/dp/${start.asin}`,
      current_price: current, old_price: old || null, image_url: image, category: surface.category, source: surface.name,
      metadata: { surface_text: text.slice(0, 600), promo_hint: promoMarker,
        flash_hint: low.includes("limited time") || low.includes("لفترة محدودة") },
    };
    const prev = unique.get(start.asin);
    const pct = old > current ? ((old-current)/old)*100 : 0;
    const prevPct = prev?.old_price && prev.old_price > prev.current_price ? ((prev.old_price-prev.current_price)/prev.old_price)*100 : -1;
    if (!prev || pct > prevPct) unique.set(start.asin, deal);
  }
  return [...unique.values()];
}

export function parseAmazon(html: string, surface: Surface): DealCandidate[] {
  return surface.name === "goldbox" ? parseGoldbox(html, surface) : parseSearch(html, surface);
}

export async function fetchAmazonSurface(surface: Surface): Promise<{text: string; latency: number}> {
  const started = Date.now();
  const res = await fetch(surface.url, {
    headers: {
      "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
      "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
      "accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
      "cache-control": "no-cache",
    },
    redirect: "follow",

    /*
     * AMAZON_DISCOVERY_FETCH_TIMEOUT_V1
     *
     * One stalled Amazon request must never block
     * the whole minute-by-minute discovery cycle.
     */
    signal:
      AbortSignal.timeout(12000),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`amazon_http_${res.status}`);
  if (isProtectedPage(text)) throw new Error("amazon_protection");
  if (text.length < 1000) throw new Error("amazon_short_response");
  return { text, latency: Date.now() - started };
}
