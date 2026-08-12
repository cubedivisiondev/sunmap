// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 PUDDY Inc.
/**
 * SUNMAP - the location stack.
 *
 * A sunrise time is a statement about ONE observer standing on ONE patch of
 * ground. Get the observer wrong and every number the engine prints is wrong,
 * silently and plausibly. That is why this module exists as its own file with
 * its own contract: it is the input half of the SUNMAP data contract.
 *
 * It emits, and only ever emits, this shape:
 *
 *   { lat, lon, alt, tz, label, source }
 *     lat    degrees north, WGS84, positive north
 *     lon    degrees east,  WGS84, positive east (engine convention, geo[0])
 *     alt    metres above mean sea level (engine convention, geo[2])
 *     tz     IANA zone id, e.g. "America/Los_Angeles"
 *     label  human string for the UI
 *     source "gps" | "ip" | "search" | "stored" | "default"
 *
 * Plus honesty fields that are additive to the contract and safe to ignore:
 *     alt_source   "gps" | "dem" | "default"
 *     tz_source    "device" | "provider" | "table"
 *     tz_ref_km    distance to the tzdata reference point used, or null when
 *                  no reference point was consulted (provider zone, device
 *                  zone, or a country with exactly one zone). null means "no
 *                  distance applies", never "zero distance".
 *     accuracy_m   horizontal accuracy when the provider reports one
 *     approx       true when the point is a city-centre reference, not the spot
 *     tz_basis     "provider" | "device" | "country" | "country+nearest" |
 *                  "nearest" - how firm the zone actually is
 *
 * RENDERING CONTRACT. label and sub originate in OpenStreetMap, which is
 * user-editable, so treat them as untrusted text: render with textContent,
 * never innerHTML. This module strips control and bidi-override characters and
 * caps length at 120 chars, but it deliberately does NOT HTML-escape - escaping
 * in a data layer only yields double-escaped text in a correct consumer.
 *     tz_conflict  the zone we rejected when two sources disagreed, else null
 *     from         how the observer was ORIGINALLY obtained, which survives
 *                  the reload that turns every source into "stored"
 *
 * PROVENANCE. This is a port of STARMAP's battle-tested permanent-free stack
 * (star_map/index.html: photonSuggest / nominatimSuggest / remoteSuggest /
 * geoCacheGet / ipLocate / chooseLocation). Behaviour is preserved on purpose:
 *
 *   1. Photon (photon.komoot.io) autocomplete PRIMARY, biased to the stored
 *      location so "main street" means the one near you.
 *   2. Nominatim (nominatim.openstreetmap.org) AUTOMATIC fallback on Photon
 *      error or empty result.
 *   3. An on-device list as the final offline fallback.
 *   4. 7-day localStorage cache, 400-entry cap, so repeat and prefix typing
 *      never re-hits the network.
 *   5. Suggestions carry their own lat/lon, so choosing one makes NO second
 *      network call.
 *   6. 250 ms debounce, and a defensive skip of any suggestion without a
 *      usable string label.
 *   7. NO API KEY, no metered provider, anywhere. STARMAP ran a keyed metered
 *      geocoder once; a throttle broke search outright and the free tier
 *      burned down. That provider was removed and stays removed. This is a
 *      hard constraint, not a preference.
 *
 * WHAT SUNMAP ADDS OVER STARMAP. STARMAP needs a point. SUNMAP needs a point,
 * a TIMEZONE, and an ALTITUDE, because both change the answer:
 *   - The timezone decides which local calendar day an event belongs to, and
 *     an hour of error moves every printed time by an hour.
 *   - Altitude moves the horizon down. Roughly 0.0345 * sqrt(h_metres) degrees
 *     of horizon dip, which at 340 m is about 0.64 deg, which at mid latitudes
 *     is a few minutes of sunrise. A product that prints seconds cannot shrug
 *     that off.
 *
 * TIMEZONE ACCURACY - THE HONEST LIMIT. When the chosen point is near the user
 * (or a provider hands us a zone), the zone is exact. Otherwise the zone is
 * INFERRED by nearest tzdata reference point, the same approach STARMAP bakes
 * in. That is a Voronoi partition over 312 principal-city points, and it is
 * simply wrong near borders and inside enclaves. A measured example: 37.75 N,
 * 101.8 W is Grant County, Kansas, which keeps Central time, and this table
 * hands back America/Denver because Denver's reference point is 354 km away
 * and Chicago's is further. Indiana, the Arizona / Utah / Navajo boundaries,
 * Xinjiang, and the Australian border towns break it the same way. The emitted
 * tz_source and tz_ref_km say which case you are in: "table" with a large
 * tz_ref_km is a guess wearing a zone name. Show the zone in the UI and let
 * the user override it. Do not pretend inference is a lookup.
 *
 * ALTITUDE. GPS altitude is used when the device reports one. Otherwise the
 * altitude is 0 and alt_source says "default" - we do not invent elevations.
 * An OPTIONAL keyless DEM refinement (Open-Meteo, Copernicus DEM 90 m) runs
 * after the location is already emitted, so it never delays a pick and never
 * counts as the "second network call" that rule 5 forbids. It never overwrites
 * a GPS altitude, and on any failure the altitude stays 0 and stays honest.
 *
 * USAGE
 *   import * as Geo from './sunmap-geo.js';
 *   Geo.onChange(loc => render(loc));
 *   await Geo.initLocation();
 *   const res = await Geo.suggest(inputValue);   // debounced 250 ms
 *   if (res.stale) return;                       // a newer query superseded it
 *   Geo.chooseLocation(res[0]);
 *
 * Network endpoints verified live 2026-08-09: Photon 200 with
 * Access-Control-Allow-Origin *, Nominatim 200 with ACAO *, get.geojs.io 200
 * with ACAO *, ipinfo.io/json 200 with ACAO *, api.open-meteo.com/v1/elevation
 * 200 with ACAO *. All keyless.
 */

/* ------------------------------------------------------------------ config */

const LS_GEO = 'sunmap.geo';
const LS_CACHE = 'sunmap.geocache';
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const CACHE_MAX = 400;
const DEBOUNCE_MS = 250;
const MIN_QUERY = 3;
const MAX_ITEMS = 10;
const GPS_TIMEOUT_MS = 10000;
const NET_TIMEOUT_MS = 8000;

/** How close a point must be to the user's own fix before we trust the
 *  browser's own timezone for it. 100 km is inside one zone almost everywhere
 *  that is not a border town, and border towns are exactly the case we refuse
 *  to guess about. */
const NEAR_KM = 100;

/** Attribution string. OpenStreetMap data is ODbL - if you show results, show
 *  this. STARMAP renders it as the last row of the suggestion list. */
export const ATTRIBUTION = 'Location search by OpenStreetMap (Photon + Nominatim)';

/** The default observer, for a visitor who has not shared a location: the
 *  Empire State Building. A real, fixed, unambiguous point rather than a city
 *  centroid, so "nowhere chosen yet" is still somewhere a person can stand.
 *  render.py hardcodes these same coordinates, so the prerendered page and a
 *  first-visit-before-geolocation page agree to the second. */
const DEFAULT_LOCATION = {
  lat: 40.748440, lon: -73.985664, alt: 0, tz: 'America/New_York',
  label: 'Empire State Building', source: 'default',
  alt_source: 'default', tz_source: 'table', tz_ref_km: 0, approx: true
};

const config = {
  autoDetect: true,   // on first visit with nothing stored, try IP
  elevation: true,    // refine altitude from a DEM after emitting
  defaultLocation: DEFAULT_LOCATION
};

/* ------------------------------------------------------- tzdata reference --
 * IANA zone id -> [lat, lon] principal location, parsed from
 * data/zone1970.tab (tzdb, public domain). 312 zones. Generated, not typed:
 * the ISO 6709 coordinates in column 2 converted to signed degrees, rounded
 * to 4 decimals (about 11 m, far finer than a "principal city" means).
 * Regenerate whenever data/zone1970.tab is updated from tzdb.
 */
const ZONE_POS = {
"Europe/Andorra":[42.5,1.5167],"Asia/Dubai":[25.3,55.3],"Asia/Kabul":[34.5167,69.2],
"Europe/Tirane":[41.3333,19.8333],"Asia/Yerevan":[40.1833,44.5],"Antarctica/Casey":[-66.2833,110.5167],
"Antarctica/Davis":[-68.5833,77.9667],"Antarctica/Mawson":[-67.6,62.8833],"Antarctica/Palmer":[-64.8,-64.1],
"Antarctica/Rothera":[-67.5667,-68.1333],"Antarctica/Troll":[-72.0114,2.535],
"Antarctica/Vostok":[-78.4,106.9],"America/Argentina/Buenos_Aires":[-34.6,-58.45],
"America/Argentina/Cordoba":[-31.4,-64.1833],"America/Argentina/Salta":[-24.7833,-65.4167],
"America/Argentina/Jujuy":[-24.1833,-65.3],"America/Argentina/Tucuman":[-26.8167,-65.2167],
"America/Argentina/Catamarca":[-28.4667,-65.7833],"America/Argentina/La_Rioja":[-29.4333,-66.85],
"America/Argentina/San_Juan":[-31.5333,-68.5167],"America/Argentina/Mendoza":[-32.8833,-68.8167],
"America/Argentina/San_Luis":[-33.3167,-66.35],"America/Argentina/Rio_Gallegos":[-51.6333,-69.2167],
"America/Argentina/Ushuaia":[-54.8,-68.3],"Pacific/Pago_Pago":[-14.2667,-170.7],
"Europe/Vienna":[48.2167,16.3333],"Australia/Lord_Howe":[-31.55,159.0833],
"Antarctica/Macquarie":[-54.5,158.95],"Australia/Hobart":[-42.8833,147.3167],
"Australia/Melbourne":[-37.8167,144.9667],"Australia/Sydney":[-33.8667,151.2167],
"Australia/Broken_Hill":[-31.95,141.45],"Australia/Brisbane":[-27.4667,153.0333],
"Australia/Lindeman":[-20.2667,149.0],"Australia/Adelaide":[-34.9167,138.5833],
"Australia/Darwin":[-12.4667,130.8333],"Australia/Perth":[-31.95,115.85],
"Australia/Eucla":[-31.7167,128.8667],"Asia/Baku":[40.3833,49.85],"America/Barbados":[13.1,-59.6167],
"Asia/Dhaka":[23.7167,90.4167],"Europe/Brussels":[50.8333,4.3333],"Europe/Sofia":[42.6833,23.3167],
"Atlantic/Bermuda":[32.2833,-64.7667],"America/La_Paz":[-16.5,-68.15],"America/Noronha":[-3.85,-32.4167],
"America/Belem":[-1.45,-48.4833],"America/Fortaleza":[-3.7167,-38.5],"America/Recife":[-8.05,-34.9],
"America/Araguaina":[-7.2,-48.2],"America/Maceio":[-9.6667,-35.7167],"America/Bahia":[-12.9833,-38.5167],
"America/Sao_Paulo":[-23.5333,-46.6167],"America/Campo_Grande":[-20.45,-54.6167],
"America/Cuiaba":[-15.5833,-56.0833],"America/Santarem":[-2.4333,-54.8667],
"America/Porto_Velho":[-8.7667,-63.9],"America/Boa_Vista":[2.8167,-60.6667],
"America/Manaus":[-3.1333,-60.0167],"America/Eirunepe":[-6.6667,-69.8667],
"America/Rio_Branco":[-9.9667,-67.8],"Asia/Thimphu":[27.4667,89.65],"Europe/Minsk":[53.9,27.5667],
"America/Belize":[17.5,-88.2],"America/St_Johns":[47.5667,-52.7167],"America/Halifax":[44.65,-63.6],
"America/Glace_Bay":[46.2,-59.95],"America/Moncton":[46.1,-64.7833],"America/Goose_Bay":[53.3333,-60.4167],
"America/Toronto":[43.65,-79.3833],"America/Iqaluit":[63.7333,-68.4667],"America/Winnipeg":[49.8833,-97.15],
"America/Resolute":[74.6956,-94.8292],"America/Rankin_Inlet":[62.8167,-92.0831],
"America/Regina":[50.4,-104.65],"America/Swift_Current":[50.2833,-107.8333],
"America/Edmonton":[53.55,-113.4667],"America/Cambridge_Bay":[69.1139,-105.0528],
"America/Inuvik":[68.3497,-133.7167],"America/Vancouver":[49.2667,-123.1167],
"America/Dawson_Creek":[55.7667,-120.2333],"America/Fort_Nelson":[58.8,-122.7],
"America/Whitehorse":[60.7167,-135.05],"America/Dawson":[64.0667,-139.4167],
"Europe/Zurich":[47.3833,8.5333],"Africa/Abidjan":[5.3167,-4.0333],"Pacific/Rarotonga":[-21.2333,-159.7667],
"America/Santiago":[-33.45,-70.6667],"America/Coyhaique":[-45.5667,-72.0667],
"America/Punta_Arenas":[-53.15,-70.9167],"Pacific/Easter":[-27.15,-109.4333],
"Asia/Shanghai":[31.2333,121.4667],"Asia/Urumqi":[43.8,87.5833],"America/Bogota":[4.6,-74.0833],
"America/Costa_Rica":[9.9333,-84.0833],"America/Havana":[23.1333,-82.3667],
"Atlantic/Cape_Verde":[14.9167,-23.5167],"Asia/Nicosia":[35.1667,33.3667],"Asia/Famagusta":[35.1167,33.95],
"Europe/Prague":[50.0833,14.4333],"Europe/Berlin":[52.5,13.3667],"America/Santo_Domingo":[18.4667,-69.9],
"Africa/Algiers":[36.7833,3.05],"America/Guayaquil":[-2.1667,-79.8333],"Pacific/Galapagos":[-0.9,-89.6],
"Europe/Tallinn":[59.4167,24.75],"Africa/Cairo":[30.05,31.25],"Africa/El_Aaiun":[27.15,-13.2],
"Europe/Madrid":[40.4,-3.6833],"Africa/Ceuta":[35.8833,-5.3167],"Atlantic/Canary":[28.1,-15.4],
"Europe/Helsinki":[60.1667,24.9667],"Pacific/Fiji":[-18.1333,178.4167],"Atlantic/Stanley":[-51.7,-57.85],
"Pacific/Kosrae":[5.3167,162.9833],"Atlantic/Faroe":[62.0167,-6.7667],"Europe/Paris":[48.8667,2.3333],
"Europe/London":[51.5083,-0.1253],"Asia/Tbilisi":[41.7167,44.8167],"America/Cayenne":[4.9333,-52.3333],
"Europe/Gibraltar":[36.1333,-5.35],"America/Nuuk":[64.1833,-51.7333],
"America/Danmarkshavn":[76.7667,-18.6667],"America/Scoresbysund":[70.4833,-21.9667],
"America/Thule":[76.5667,-68.7833],"Europe/Athens":[37.9667,23.7167],
"Atlantic/South_Georgia":[-54.2667,-36.5333],"America/Guatemala":[14.6333,-90.5167],
"Pacific/Guam":[13.4667,144.75],"Africa/Bissau":[11.85,-15.5833],"America/Guyana":[6.8,-58.1667],
"Asia/Hong_Kong":[22.2833,114.15],"America/Tegucigalpa":[14.1,-87.2167],
"America/Port-au-Prince":[18.5333,-72.3333],"Europe/Budapest":[47.5,19.0833],"Asia/Jakarta":[-6.1667,106.8],
"Asia/Pontianak":[-0.0333,109.3333],"Asia/Makassar":[-5.1167,119.4],"Asia/Jayapura":[-2.5333,140.7],
"Europe/Dublin":[53.3333,-6.25],"Asia/Jerusalem":[31.7806,35.2239],"Asia/Kolkata":[22.5333,88.3667],
"Indian/Chagos":[-7.3333,72.4167],"Asia/Baghdad":[33.35,44.4167],"Asia/Tehran":[35.6667,51.4333],
"Europe/Rome":[41.9,12.4833],"America/Jamaica":[17.9681,-76.7933],"Asia/Amman":[31.95,35.9333],
"Asia/Tokyo":[35.6544,139.7447],"Africa/Nairobi":[-1.2833,36.8167],"Asia/Bishkek":[42.9,74.6],
"Pacific/Tarawa":[1.4167,173.0],"Pacific/Kanton":[-2.7833,-171.7167],
"Pacific/Kiritimati":[1.8667,-157.3333],"Asia/Pyongyang":[39.0167,125.75],"Asia/Seoul":[37.55,126.9667],
"Asia/Almaty":[43.25,76.95],"Asia/Qyzylorda":[44.8,65.4667],"Asia/Qostanay":[53.2,63.6167],
"Asia/Aqtobe":[50.2833,57.1667],"Asia/Aqtau":[44.5167,50.2667],"Asia/Atyrau":[47.1167,51.9333],
"Asia/Oral":[51.2167,51.35],"Asia/Beirut":[33.8833,35.5],"Asia/Colombo":[6.9333,79.85],
"Africa/Monrovia":[6.3,-10.7833],"Europe/Vilnius":[54.6833,25.3167],"Europe/Riga":[56.95,24.1],
"Africa/Tripoli":[32.9,13.1833],"Africa/Casablanca":[33.65,-7.5833],"Europe/Chisinau":[47.0,28.8333],
"Pacific/Kwajalein":[9.0833,167.3333],"Asia/Yangon":[16.7833,96.1667],"Asia/Ulaanbaatar":[47.9167,106.8833],
"Asia/Hovd":[48.0167,91.65],"Asia/Macau":[22.1972,113.5417],"America/Martinique":[14.6,-61.0833],
"Europe/Malta":[35.9,14.5167],"Indian/Mauritius":[-20.1667,57.5],"Indian/Maldives":[4.1667,73.5],
"America/Mexico_City":[19.4,-99.15],"America/Cancun":[21.0833,-86.7667],"America/Merida":[20.9667,-89.6167],
"America/Monterrey":[25.6667,-100.3167],"America/Matamoros":[25.8333,-97.5],
"America/Chihuahua":[28.6333,-106.0833],"America/Ciudad_Juarez":[31.7333,-106.4833],
"America/Ojinaga":[29.5667,-104.4167],"America/Mazatlan":[23.2167,-106.4167],
"America/Bahia_Banderas":[20.8,-105.25],"America/Hermosillo":[29.0667,-110.9667],
"America/Tijuana":[32.5333,-117.0167],"Asia/Kuching":[1.55,110.3333],"Africa/Maputo":[-25.9667,32.5833],
"Africa/Windhoek":[-22.5667,17.1],"Pacific/Noumea":[-22.2667,166.45],"Pacific/Norfolk":[-29.05,167.9667],
"Africa/Lagos":[6.45,3.4],"America/Managua":[12.15,-86.2833],"Asia/Kathmandu":[27.7167,85.3167],
"Pacific/Nauru":[-0.5167,166.9167],"Pacific/Niue":[-19.0167,-169.9167],
"Pacific/Auckland":[-36.8667,174.7667],"Pacific/Chatham":[-43.95,-176.55],
"America/Panama":[8.9667,-79.5333],"America/Lima":[-12.05,-77.05],"Pacific/Tahiti":[-17.5333,-149.5667],
"Pacific/Marquesas":[-9.0,-139.5],"Pacific/Gambier":[-23.1333,-134.95],
"Pacific/Port_Moresby":[-9.5,147.1667],"Pacific/Bougainville":[-6.2167,155.5667],
"Asia/Manila":[14.5867,120.9678],"Asia/Karachi":[24.8667,67.05],"Europe/Warsaw":[52.25,21.0],
"America/Miquelon":[47.05,-56.3333],"Pacific/Pitcairn":[-25.0667,-130.0833],
"America/Puerto_Rico":[18.4683,-66.1061],"Asia/Gaza":[31.5,34.4667],"Asia/Hebron":[31.5333,35.095],
"Europe/Lisbon":[38.7167,-9.1333],"Atlantic/Madeira":[32.6333,-16.9],"Atlantic/Azores":[37.7333,-25.6667],
"Pacific/Palau":[7.3333,134.4833],"America/Asuncion":[-25.2667,-57.6667],"Asia/Qatar":[25.2833,51.5333],
"Europe/Bucharest":[44.4333,26.1],"Europe/Belgrade":[44.8333,20.5],"Europe/Kaliningrad":[54.7167,20.5],
"Europe/Moscow":[55.7558,37.6178],"Europe/Simferopol":[44.95,34.1],"Europe/Kirov":[58.6,49.65],
"Europe/Volgograd":[48.7333,44.4167],"Europe/Astrakhan":[46.35,48.05],"Europe/Saratov":[51.5667,46.0333],
"Europe/Ulyanovsk":[54.3333,48.4],"Europe/Samara":[53.2,50.15],"Asia/Yekaterinburg":[56.85,60.6],
"Asia/Omsk":[55.0,73.4],"Asia/Novosibirsk":[55.0333,82.9167],"Asia/Barnaul":[53.3667,83.75],
"Asia/Tomsk":[56.5,84.9667],"Asia/Novokuznetsk":[53.75,87.1167],"Asia/Krasnoyarsk":[56.0167,92.8333],
"Asia/Irkutsk":[52.2667,104.3333],"Asia/Chita":[52.05,113.4667],"Asia/Yakutsk":[62.0,129.6667],
"Asia/Khandyga":[62.6564,135.5539],"Asia/Vladivostok":[43.1667,131.9333],"Asia/Ust-Nera":[64.5603,143.2267],
"Asia/Magadan":[59.5667,150.8],"Asia/Sakhalin":[46.9667,142.7],"Asia/Srednekolymsk":[67.4667,153.7167],
"Asia/Kamchatka":[53.0167,158.65],"Asia/Anadyr":[64.75,177.4833],"Asia/Riyadh":[24.6333,46.7167],
"Pacific/Guadalcanal":[-9.5333,160.2],"Africa/Khartoum":[15.6,32.5333],"Asia/Singapore":[1.2833,103.85],
"America/Paramaribo":[5.8333,-55.1667],"Africa/Juba":[4.85,31.6167],"Africa/Sao_Tome":[0.3333,6.7333],
"America/El_Salvador":[13.7,-89.2],"Asia/Damascus":[33.5,36.3],"America/Grand_Turk":[21.4667,-71.1333],
"Africa/Ndjamena":[12.1167,15.05],"Asia/Bangkok":[13.75,100.5167],"Asia/Dushanbe":[38.5833,68.8],
"Pacific/Fakaofo":[-9.3667,-171.2333],"Asia/Dili":[-8.55,125.5833],"Asia/Ashgabat":[37.95,58.3833],
"Africa/Tunis":[36.8,10.1833],"Pacific/Tongatapu":[-21.1333,-175.2],"Europe/Istanbul":[41.0167,28.9667],
"Asia/Taipei":[25.05,121.5],"Europe/Kyiv":[50.4333,30.5167],"America/New_York":[40.7142,-74.0064],
"America/Detroit":[42.3314,-83.0458],"America/Kentucky/Louisville":[38.2542,-85.7594],
"America/Kentucky/Monticello":[36.8297,-84.8492],"America/Indiana/Indianapolis":[39.7683,-86.1581],
"America/Indiana/Vincennes":[38.6772,-87.5286],"America/Indiana/Winamac":[41.0514,-86.6031],
"America/Indiana/Marengo":[38.3756,-86.3447],"America/Indiana/Petersburg":[38.4919,-87.2786],
"America/Indiana/Vevay":[38.7478,-85.0672],"America/Chicago":[41.85,-87.65],
"America/Indiana/Tell_City":[37.9531,-86.7614],"America/Indiana/Knox":[41.2958,-86.625],
"America/Menominee":[45.1078,-87.6142],"America/North_Dakota/Center":[47.1164,-101.2992],
"America/North_Dakota/New_Salem":[46.845,-101.4108],"America/North_Dakota/Beulah":[47.2642,-101.7778],
"America/Denver":[39.7392,-104.9842],"America/Boise":[43.6136,-116.2025],
"America/Phoenix":[33.4483,-112.0733],"America/Los_Angeles":[34.0522,-118.2428],
"America/Anchorage":[61.2181,-149.9003],"America/Juneau":[58.3019,-134.4197],
"America/Sitka":[57.1764,-135.3019],"America/Metlakatla":[55.1269,-131.5764],
"America/Yakutat":[59.5469,-139.7272],"America/Nome":[64.5011,-165.4064],"America/Adak":[51.88,-176.6581],
"Pacific/Honolulu":[21.3069,-157.8583],"America/Montevideo":[-34.9092,-56.2125],
"Asia/Samarkand":[39.6667,66.8],"Asia/Tashkent":[41.3333,69.3],"America/Caracas":[10.5,-66.9333],
"Asia/Ho_Chi_Minh":[10.75,106.6667],"Pacific/Efate":[-17.6667,168.4167],"Pacific/Apia":[-13.8333,-171.7333],
"Africa/Johannesburg":[-26.25,28.0]
};

/** Alternate names for the SAME reference point. Strictly aliases: a spelling,
 *  an exonym, or an abbreviation for the very city the zone is named after.
 *  Never a different city - mapping "Boston" to America/New_York would put the
 *  observer 300 km out to sea, and a wrong observer is worse than no match. */
const ZONE_ALIASES = {
  'America/New_York': ['New York City', 'NYC', 'New York'],
  'America/Los_Angeles': ['LA', 'Los Angeles'],
  'America/Mexico_City': ['CDMX', 'Ciudad de Mexico', 'Mexico City'],
  'America/Sao_Paulo': ['Sao Paulo'],
  'America/Bogota': ['Santa Fe de Bogota'],
  'Europe/Kyiv': ['Kiev'],
  'Europe/Lisbon': ['Lisboa'],
  'Europe/Rome': ['Roma'],
  'Europe/Moscow': ['Moskva'],
  'Europe/Prague': ['Praha'],
  'Europe/Vienna': ['Wien'],
  'Europe/Warsaw': ['Warszawa'],
  'Europe/Brussels': ['Bruxelles', 'Brussel'],
  'Europe/Athens': ['Athina'],
  'Europe/Bucharest': ['Bucuresti'],
  'Europe/Belgrade': ['Beograd'],
  'Europe/Zurich': ['Zuerich'],
  'Europe/Tirane': ['Tirana'],
  'Europe/Chisinau': ['Kishinev'],
  'Asia/Kolkata': ['Calcutta'],
  'Asia/Ho_Chi_Minh': ['Saigon'],
  'Asia/Yangon': ['Rangoon'],
  'Asia/Almaty': ['Alma-Ata'],
  'Asia/Ashgabat': ['Ashkhabad'],
  'Asia/Kathmandu': ['Katmandu'],
  'Asia/Makassar': ['Ujung Pandang'],
  'Pacific/Honolulu': ['Hawaii']
};

/* --------------------------------------------------------------- geometry */

const TO_RAD = Math.PI / 180;
const EARTH_KM = 6371.0088;

/** Great-circle distance in km. Haversine, with longitude difference wrapped
 *  into [-180, 180] - the equirectangular shortcut STARMAP uses breaks across
 *  the antimeridian, which is precisely where the Pacific zones live. */
function distKm(aLat, aLon, bLat, bLon) {
  const dLat = (bLat - aLat) * TO_RAD;
  const dLon = (((bLon - aLon + 540) % 360) - 180) * TO_RAD;
  const s1 = Math.sin(dLat / 2), s2 = Math.sin(dLon / 2);
  const h = s1 * s1 + Math.cos(aLat * TO_RAD) * Math.cos(bLat * TO_RAD) * s2 * s2;
  return 2 * EARTH_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Nearest tzdata reference point. Returns { tz, km }. 312 haversines is a
 *  few microseconds, so there is no reason to approximate. */
export function nearestTimeZone(lat, lon) {
  let best = null, bestKm = Infinity;
  for (const z in ZONE_POS) {
    const p = ZONE_POS[z];
    const km = distKm(lat, lon, p[0], p[1]);
    if (km < bestKm) { bestKm = km; best = z; }
  }
  return { tz: best, km: Math.round(bestKm * 10) / 10 };
}

/* ------------------------------------------------------------- timezone --- */

function validTz(z) {
  if (!z || typeof z !== 'string') return false;
  try { new Intl.DateTimeFormat('en', { timeZone: z }); return true; }
  catch (_) { return false; }
}

function deviceTz() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; }
  catch (_) { return ''; }
}

/** The last known position of the USER, from GPS or IP: { lat, lon, tz }.
 *  Used only to decide whether the browser's own timezone applies to a chosen
 *  point, and to detect a device/provider zone disagreement. */
let userFix = null;

/**
 * Resolve a point to an IANA zone.
 *  - A zone handed to us by the device or a geo provider wins outright.
 *  - Otherwise, if the point sits within NEAR_KM of the user's own fix, the
 *    browser's zone is the truth for it (the OS knows what the table cannot).
 *  - Otherwise infer from the nearest tzdata reference point, and SAY that is
 *    what happened. See the border caveat in the file header.
 *
 * When the device zone and the zone the IP provider reported for the same
 * fix disagree, one of them is stale: either the laptop has not caught up
 * with a flight, or the IP is behind a VPN. We take the device zone, because
 * the OS is the only one of the two that knows where the hardware is, and we
 * report the loser in tz_conflict so the UI can offer it. Silently picking
 * and hiding the disagreement is the one thing we will not do.
 */
function deriveTz(lat, lon, hintTz, hintSource, countryCode) {
  if (validTz(hintTz)) {
    return { tz: hintTz, tz_source: hintSource || 'provider', tz_ref_km: null, tz_basis: 'provider', tz_conflict: null };
  }
  const near = zoneForPoint(lat, lon, countryCode);
  const dev = deviceTz();
  if (validTz(dev) && userFix && distKm(lat, lon, userFix.lat, userFix.lon) <= NEAR_KM) {
    const clash = (userFix.tz && validTz(userFix.tz) && userFix.tz !== dev) ? userFix.tz : null;
    return { tz: dev, tz_source: 'device', tz_ref_km: null, tz_basis: 'device', tz_conflict: clash };
  }
  if (validTz(near.tz)) {
    // When the table and the browser agree we can call it device-grade.
    const src = (dev && dev === near.tz) ? 'device' : 'table';
    return { tz: near.tz, tz_source: src, tz_ref_km: near.km, tz_basis: near.basis, tz_conflict: null };
  }
  return { tz: validTz(dev) ? dev : 'UTC', tz_source: validTz(dev) ? 'device' : 'table', tz_ref_km: null, tz_basis: 'device', tz_conflict: null };
}

/* ------------------------------------------------------------- storage --- */

function readJSON(key, fallback) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
  catch (_) { return fallback; }
}
function writeJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch (_) { return false; } // private mode / quota - never fatal
}

/** The stored observer, or null. Validated on read: a corrupt or truncated
 *  entry must not become a silently wrong sunrise. */
export function getStored() {
  const g = readJSON(LS_GEO, null);
  if (!g || !isFinite(g.lat) || !isFinite(g.lon)) return null;
  if (Math.abs(g.lat) > 90 || Math.abs(g.lon) > 180) return null;
  return normalizeLocation({
    lat: g.lat, lon: g.lon, alt: isFinite(g.alt) ? g.alt : 0,
    tz: validTz(g.tz) ? g.tz : null, label: typeof g.label === 'string' ? g.label : '',
    source: 'stored', from: g.from || g.source || null,
    alt_source: g.alt_source || 'default',
    tz_source: g.tz_source, tz_ref_km: g.tz_ref_km, tz_basis: g.tz_basis,
    accuracy_m: g.accuracy_m, approx: g.approx
  });
}

export function clearStored() {
  try { localStorage.removeItem(LS_GEO); } catch (_) {}
}

/* --------------------------------------------------------- geocode cache --
 * Query string -> suggestion array, 7 days, 400 entries, oldest evicted first.
 * Prefix typing means one search produces many near-identical queries; the
 * cache is what keeps that from being many round trips.
 */
function cacheGet(q) {
  const c = readJSON(LS_CACHE, {});
  const e = c[q];
  if (e && (Date.now() - e.t) < CACHE_TTL_MS && Array.isArray(e.r)) return e.r;
  return null;
}
function cachePut(q, r) {
  const c = readJSON(LS_CACHE, {});
  c[q] = { t: Date.now(), r: r };
  const keys = Object.keys(c);
  if (keys.length > CACHE_MAX) {
    keys.sort((a, b) => c[a].t - c[b].t)
        .slice(0, keys.length - CACHE_MAX)
        .forEach(k => { delete c[k]; });
  }
  writeJSON(LS_CACHE, c);
}

/* -------------------------------------------------------------- fetching -- */

/** fetch with a hard timeout. A geocoder that hangs is worse than one that
 *  fails, because the fallback chain never gets its turn. */
function getJSON(url, timeoutMs) {
  const ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  const t = setTimeout(() => { if (ctl) ctl.abort(); }, timeoutMs || NET_TIMEOUT_MS);
  const opts = ctl ? { signal: ctl.signal, credentials: 'omit' } : { credentials: 'omit' };
  return fetch(url, opts)
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url); return r.json(); })
    .finally(() => clearTimeout(t));
}

/* ------------------------------------------------------------ providers --- */

/* Neither Photon nor Nominatim returns a timezone, so every remote suggestion
 * arrives zoneless. We resolve one HERE, at parse time, from the country code
 * the provider DID return - the country constraint is the whole reason cc is
 * carried, and a consumer that reads item.tz (index.html's normPlace does, and
 * it drops cc on the floor) would otherwise fall back to the DEVICE zone and
 * render Tokyo's sunrise labelled America/Los_Angeles.
 *
 * The zone is stamped with its own provenance so nothing downstream can mistake
 * our inference for a provider lookup: tz_source "table", plus the basis and
 * the reference distance from zoneForPoint. chooseLocation deliberately
 * re-derives rather than trusting this, so the near-user device override still
 * wins for a point the OS actually knows about. */
function withZone(item) {
  const z = zoneForPoint(item.lat, item.lon, item.cc);
  item.tz = validTz(z.tz) ? z.tz : null;
  item.tz_source = item.tz ? 'table' : null;
  item.tz_basis = item.tz ? z.basis : null;
  item.tz_ref_km = item.tz ? z.km : null;
  return item;
}

/** Photon (komoot, OpenStreetMap). Built for type-ahead, keyless, CORS open.
 *  Biased to the stored observer so short queries resolve locally first. */
function photonSuggest(q) {
  const g = getStored() || current;
  const bias = (g && isFinite(g.lat) && isFinite(g.lon)) ? ('&lat=' + g.lat + '&lon=' + g.lon) : '';
  const url = 'https://photon.komoot.io/api/?lang=en&limit=8' + bias + '&q=' + encodeURIComponent(q);
  return getJSON(url).then(j => (j && j.features || []).map(f => {
    const p = f.properties || {};
    const c = (f.geometry || {}).coordinates || [];
    const street = (p.street && p.housenumber) ? (p.housenumber + ' ' + p.street) : p.street;
    const parts = [street, p.district, p.locality, p.city, p.county, p.state, p.postcode, p.country]
      .filter((x, i, arr) => x && x !== p.name && arr.indexOf(x) === i);
    return withZone({
      label: cleanText(p.name || parts[0] || q),
      sub: cleanText(parts.join(', ')),
      lat: Number(c[1]), lon: Number(c[0]),
      cc: p.countrycode || '', source: 'photon', approx: false
    });
  }).filter(usableItem));
}

/** Nominatim (OpenStreetMap). Fallback only - it is a fair-use service, not a
 *  type-ahead API. The browser's own User-Agent and Referer identify us; no
 *  key, no email parameter (personal contact never goes on the wire).
 *
 *  MEASURED 2026-08-09, both from curl's default User-Agent and from a browser
 *  one: HTTP 200, Access-Control-Allow-Origin *, jsonv2 with addressdetails.
 *  An earlier note in this file claimed Nominatim 403s every non-browser
 *  User-Agent; re-measurement did not reproduce that, so do NOT dismiss a
 *  failure here as a harness artifact. Nominatim does rate-limit and does
 *  block abusive agents, so a 403 or 429 means we are being throttled and the
 *  Photon-first ordering is what keeps that off the hot path. */
function nominatimSuggest(q) {
  const url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1'
            + '&accept-language=en&limit=8&q=' + encodeURIComponent(q);
  return getJSON(url).then(j => (j || []).map(d => {
    const a = d.address || {};
    const dn = String(d.display_name || '');
    const street = (a.house_number ? a.house_number + ' ' : '')
                 + (a.road || a.tourism || a.amenity || a.shop || a.building || dn.split(',')[0] || q);
    // Prefer the place's own name when it is more than a repeat of the road,
    // so 1600 Pennsylvania Avenue reads "White House" the way Photon would.
    const named = (typeof d.name === 'string' && d.name.trim() && d.name !== a.road) ? d.name.trim() : '';
    const head = named || street;
    return withZone({
      label: cleanText(head),
      sub: cleanText(dn.split(',').slice(1, 5).join(',')),
      lat: Number(d.lat), lon: Number(d.lon),
      cc: String(a.country_code || '').toUpperCase(), source: 'nominatim', approx: false
    });
  }).filter(usableItem));
}

/** Photon first, Nominatim on error OR on an empty result. Never rejects -
 *  an empty array means "the network had nothing", and the on-device matches
 *  still stand. */
function remoteSuggest(q) {
  return photonSuggest(q)
    .then(res => (res && res.length) ? res : nominatimSuggest(q).catch(() => []))
    .catch(() => nominatimSuggest(q).catch(() => []));
}

/* --------------------------------------------------------- untrusted text --
 * OpenStreetMap names are USER-EDITABLE. Photon and Nominatim hand back
 * whatever an OSM contributor typed, and this module's output goes straight
 * into the DOM and into localStorage. Three real hazards, all measured against
 * live provider shapes rather than imagined:
 *
 *   1. Markup. We do not escape here, because escaping in a data layer just
 *      produces double-escaped text in a correct consumer. The contract is:
 *      RENDER label AND sub WITH textContent, NEVER innerHTML. Enforced today
 *      in sun_map/index.html, which contains zero innerHTML.
 *   2. Bidi and control characters. A U+202E RIGHT-TO-LEFT OVERRIDE inside a
 *      place name visually reverses everything after it, including a
 *      coordinate readout rendered on the same line. textContent does not save
 *      you from that one, so it is stripped here.
 *   3. Length. An unbounded name breaks layout and bloats the persisted
 *      observer. A 4030-character label was passed through verbatim before
 *      this cap existed.
 */
const BIDI_AND_CONTROL =
  /[\u0000-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u206F\uFEFF]/g;
const TEXT_MAX = 120;

function cleanText(s) {
  if (typeof s !== 'string') return '';
  const t = s.replace(BIDI_AND_CONTROL, ' ').replace(/\s+/g, ' ').trim();
  return t.length > TEXT_MAX ? t.slice(0, TEXT_MAX - 3).trimEnd() + '...' : t;
}

/** The defensive guard STARMAP learned to need: a suggestion with no usable
 *  string label cannot be rendered and must never be pickable. */
function usableItem(it) {
  return !!it && typeof it.label === 'string' && it.label.trim().length > 0
      && isFinite(it.lat) && isFinite(it.lon)
      && Math.abs(it.lat) <= 90 && Math.abs(it.lon) <= 180;
}

/* -------------------------------------------------- on-device city base ---
 * The final offline fallback. Every entry is a tzdata principal location, so
 * the coordinates and the zone are both sourced, exact, and public domain -
 * nothing here is invented. What it is NOT is a gazetteer: it holds 312 cities,
 * one per zone, so offline picks are city-centre approximations (approx:true).
 * The moment the network answers, real results outrank these.
 */
const CITY_INDEX = (() => {
  const rows = [];
  for (const z in ZONE_POS) {
    const p = ZONE_POS[z];
    const city = (z.split('/').pop() || '').replace(/_/g, ' ');
    const names = [city].concat(ZONE_ALIASES[z] || []);
    const seen = {};
    for (const n of names) {
      const key = n.toLowerCase();
      if (seen[key]) continue;
      seen[key] = 1;
      rows.push({ name: n, low: key, zone: z, lat: p[0], lon: p[1] });
    }
  }
  return rows;
})();

/** Offline matches for a query. Prefix hits rank above substring hits, and
 *  every hit is labelled with its zone so the user can see what they are
 *  actually selecting. Synchronous - safe to call on every keystroke. */
export function localMatches(query, limit) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return [];
  const cap = limit || 4;
  const pre = [], sub = [];
  for (const c of CITY_INDEX) {
    const i = c.low.indexOf(q);
    if (i === 0) pre.push(c);
    else if (i > 0) sub.push(c);
    if (pre.length >= cap) break;
  }
  return pre.concat(sub).slice(0, cap).map(c => ({
    label: c.name,
    sub: c.zone.replace(/_/g, ' '),
    lat: c.lat, lon: c.lon,
    tz: c.zone, source: 'offline', approx: true
  }));
}

/* ------------------------------------------------------------- suggest --- */

let seqCounter = 0;
let debounceTimer = null;
let pendingResolve = null;

function mark(items, stale, query) {
  items.stale = !!stale;
  items.query = query || '';
  return items;
}

/**
 * Debounced autocomplete (250 ms). Resolves to an Array of suggestion items.
 *
 * IMPORTANT: if a newer query superseded this one, the array resolves EMPTY
 * with `.stale === true`. Check it and return early, or you will clear the
 * list the newer query is about to fill:
 *     const res = await suggest(q); if (res.stale) return;
 */
export function suggest(query) {
  return new Promise(resolve => {
    clearTimeout(debounceTimer);
    if (pendingResolve) { pendingResolve(mark([], true, query)); } // settle the superseded call
    pendingResolve = resolve;
    debounceTimer = setTimeout(() => {
      pendingResolve = null;
      suggestNow(query).then(resolve);
    }, DEBOUNCE_MS);
  });
}

/** Cancel a debounced suggest in flight (input cleared, box closed). */
export function cancelSuggest() {
  clearTimeout(debounceTimer);
  if (pendingResolve) { pendingResolve(mark([], true, '')); pendingResolve = null; }
  seqCounter++;
}

/** Undebounced autocomplete - for an Enter keypress, where waiting 250 ms is
 *  the wrong behaviour. Same result contract as suggest(). */
export function suggestNow(query) {
  const q = String(query || '').trim();
  const seq = ++seqCounter;
  if (q.length < MIN_QUERY) return Promise.resolve(mark([], false, q));

  const norm = q.toLowerCase();
  const local = localMatches(norm);
  const cached = cacheGet(norm);
  const remote = cached
    ? Promise.resolve(cached)
    : remoteSuggest(norm).then(r => { if (r && r.length) cachePut(norm, r); return r; }).catch(() => []);

  return remote.then(rem => {
    if (seq !== seqCounter) return mark([], true, q);
    // A digit in the query means a street address or a postcode - map results
    // outrank the city shortcuts. Otherwise the city shortcuts lead, because
    // "paris" should offer Paris before Paris Street.
    const addrLike = /\d/.test(q);
    const ordered = addrLike ? (rem || []).concat(local) : local.concat(rem || []);
    const seen = {};
    const out = ordered.filter(it => {
      if (!usableItem(it)) return false;
      const k = it.label + '|' + (it.sub || '');
      if (seen[k]) return false;
      seen[k] = 1;
      return true;
    }).slice(0, MAX_ITEMS);
    return mark(out, false, q);
  }).catch(() => mark(local.slice(0, MAX_ITEMS), false, q));
}

/* ------------------------------------------------------- location emit --- */

let current = null;
const listeners = new Set();

function round(n, dp) { const f = Math.pow(10, dp); return Math.round(n * f) / f; }

/** Build the canonical emitted object. Coordinates keep 6 decimals (about
 *  0.1 m) - rounding an observer is throwing away the thing this module is
 *  for. Altitude keeps 1 decimal. */
function normalizeLocation(raw) {
  const lat = round(Number(raw.lat), 6);
  const lon = round(Number(raw.lon), 6);
  const z = (raw.tz && validTz(raw.tz))
    ? { tz: raw.tz, tz_source: raw.tz_source || 'provider',
        tz_ref_km: raw.tz_ref_km == null ? null : raw.tz_ref_km,
        tz_basis: raw.tz_basis || (raw.tz_source === 'table' ? 'table' : 'provider'), tz_conflict: null }
    : deriveTz(lat, lon, null, null, raw.cc);
  const altNum = Number(raw.alt);
  const alt = isFinite(altNum) ? round(altNum, 1) : 0;
  return {
    lat: lat,
    lon: lon,
    alt: alt,
    tz: z.tz,
    // cleanText again, not only at the provider parse: a label can also arrive
    // from a caller-built object or from a localStorage entry written by an
    // older build, and neither has been through the provider path.
    label: cleanText(raw.label) || labelFor(lat, lon, z.tz),
    source: raw.source || 'search',
    alt_source: raw.alt_source || (alt ? 'gps' : 'default'),
    tz_source: z.tz_source,
    tz_ref_km: z.tz_ref_km == null ? null : z.tz_ref_km,
    // isFinite(null) is true in JavaScript, so a null accuracy must be tested
    // explicitly or "unknown" silently becomes a confident "0 metres".
    accuracy_m: (raw.accuracy_m != null && isFinite(raw.accuracy_m)) ? Math.round(raw.accuracy_m) : null,
    approx: !!raw.approx,
    tz_basis: z.tz_basis || null,
    tz_conflict: raw.tz_conflict || z.tz_conflict || null,
    // How this observer was ORIGINALLY obtained. `source` becomes "stored" on
    // the next page load, so without this the fact that it came from GPS is
    // lost and later timezone inference quietly downgrades to the table.
    from: raw.from || raw.source || 'search'
  };
}

function labelFor(lat, lon, tz) {
  const city = (String(tz || '').split('/').pop() || '').replace(/_/g, ' ');
  return city || (lat.toFixed(4) + ', ' + lon.toFixed(4));
}

/** Emit, and persist unless this is only the placeholder default. Persisting
 *  the default would be a quiet trap: the next visit would read it back as a
 *  "stored" observer and never auto-detect again, so every future session
 *  would show New York's sunrise to someone in Lisbon. */
function emit(loc) {
  current = loc;
  if (loc.source !== 'default') writeJSON(LS_GEO, Object.assign({ v: 1 }, loc));
  listeners.forEach(cb => { try { cb(loc); } catch (_) {} });
  return loc;
}

/**
 * Subscribe to location changes. Fires on every resolved location, including
 * the later DEM altitude refinement. Returns an unsubscribe function. If a
 * location already exists, the callback is invoked once on the next microtask
 * so a late-mounting UI does not miss it.
 */
export function onChange(cb) {
  if (typeof cb !== 'function') return () => {};
  listeners.add(cb);
  if (current) Promise.resolve().then(() => { if (listeners.has(cb)) { try { cb(current); } catch (_) {} } });
  return () => listeners.delete(cb);
}

/** The location in force right now, or null before initLocation(). */
export function getCurrent() { return current; }

/**
 * Commit a chosen place. Accepts a suggestion item from suggest(), or any
 * plain { lat, lon, tz?, alt?, label? }.
 *
 * Makes NO network call to resolve the pick - the suggestion already carries
 * its coordinates. The optional DEM altitude lookup fires AFTER the location
 * is emitted, and only when no real altitude is known.
 */
export function chooseLocation(item, opts) {
  if (!item || !isFinite(Number(item.lat)) || !isFinite(Number(item.lon))) {
    throw new Error('chooseLocation: an item with finite lat and lon is required');
  }
  const o = opts || {};
  // A zone is passed straight through ONLY when a provider actually supplied
  // it. Our own table-derived zones (offline picks, and the one withZone()
  // stamps on every remote suggestion) are re-derived instead, so the near-user
  // device override and the country constraint both still get their say. The
  // test is the item's declared provenance, never a guess from item.source -
  // a suggestion that says "table" must not be re-labelled "provider" one
  // function call later.
  const ourOwn = item.tz_source === 'table' || item.source === 'offline';
  const providerTz = (item.tz && !ourOwn) ? item.tz : null;
  const loc = normalizeLocation({
    lat: item.lat,
    lon: item.lon,
    alt: isFinite(item.alt) ? item.alt : 0,
    alt_source: isFinite(item.alt) && item.alt !== 0 ? (item.alt_source || 'gps') : 'default',
    tz: providerTz,
    cc: item.cc,
    tz_source: providerTz ? 'provider' : undefined,
    tz_basis: providerTz ? 'provider' : undefined,
    tz_ref_km: undefined,
    label: item.label,
    source: o.source || 'search',
    approx: !!item.approx
  });
  emit(loc);
  if (config.elevation && loc.alt_source === 'default') refineAltitude(loc);
  return loc;
}

/* ------------------------------------------------------------ device GPS -- */

/**
 * Browser geolocation, high accuracy. This is the precise option: it is the
 * only source that can put the observer on the right side of a hill.
 *
 * Precise device geolocation returns POSITION_UNAVAILABLE on plenty of
 * desktops even with permission granted (the OS provider simply has no fix),
 * so on ANY failure - denied, unavailable, timeout, or no API at all - this
 * falls through to the IP chain rather than dead-ending. Pass
 * { fallbackToIP: false } to get the raw rejection instead.
 */
export function useDeviceLocation(opts) {
  const o = opts || {};
  const fallback = o.fallbackToIP !== false;
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      // "No API at all" is one of the failures the fallback exists for, so it
      // takes the same road as a denial rather than dead-ending here.
      if (fallback) return useIPLocation().then(resolve, reject);
      return reject(new Error('geolocation unavailable'));
    }
    navigator.geolocation.getCurrentPosition(
      pos => {
        const c = pos.coords;
        userFix = { lat: c.latitude, lon: c.longitude, tz: deviceTz() };
        const hasAlt = isFinite(c.altitude) && c.altitude !== null;
        const loc = normalizeLocation({
          lat: c.latitude, lon: c.longitude,
          // Device altitude is WGS84 ellipsoidal on most platforms, not mean
          // sea level; the difference (geoid undulation) is tens of metres,
          // which is well under the accuracy that matters for horizon dip.
          alt: hasAlt ? c.altitude : 0,
          alt_source: hasAlt ? 'gps' : 'default',
          tz: deviceTz(), tz_source: 'device',
          label: 'Your location', source: 'gps',
          accuracy_m: c.accuracy, approx: false
        });
        emit(loc);
        if (config.elevation && loc.alt_source === 'default') refineAltitude(loc);
        resolve(loc);
      },
      err => {
        if (!fallback) return reject(err instanceof Error ? err : new Error('geolocation failed: ' + (err && err.message || err && err.code || 'unknown')));
        useIPLocation().then(resolve, reject);
      },
      { enableHighAccuracy: true, timeout: o.timeout || GPS_TIMEOUT_MS, maximumAge: 600000 }
    );
  });
}

/* -------------------------------------------------------------- IP chain -- */

/**
 * Approximate location by network address. Two keyless, CORS-open, HTTPS
 * providers in series so this never depends on one service. Both hand back an
 * IANA timezone, which is why an IP fix gets tz_source "provider" rather than
 * an inferred zone.
 *
 * City-level at best (get.geojs.io reports an accuracy radius in km), so the
 * result is marked approx and altitude stays unknown. Good enough to open the
 * app on the right continent, never good enough to call it the observer.
 */
export function useIPLocation() {
  return getJSON('https://get.geojs.io/v1/ip/geo.json')
    .then(j => {
      const la = parseFloat(j && j.latitude), lo = parseFloat(j && j.longitude);
      if (!isFinite(la) || !isFinite(lo)) throw new Error('geojs: no coordinates');
      // get.geojs.io passes through MaxMind's accuracy_radius, which is in
      // KILOMETRES. A live call from Los Angeles returns 20, meaning a 20 km
      // circle - which is exactly why an IP fix is never the final observer.
      const km = parseFloat(j && j.accuracy);
      return {
        lat: la, lon: lo, tz: j.timezone || '', cc: j.country_code || '',
        label: ((j.city ? j.city + ', ' : '') + (j.region || j.country || '')).trim().replace(/,$/, '') || 'Your area',
        accuracy_m: isFinite(km) ? km * 1000 : null
      };
    })
    .catch(() => getJSON('https://ipinfo.io/json').then(j => {
      const ll = String((j && j.loc) || '').split(',');
      const la = parseFloat(ll[0]), lo = parseFloat(ll[1]);
      if (!isFinite(la) || !isFinite(lo)) throw new Error('ipinfo: no coordinates');
      return {
        lat: la, lon: lo, tz: j.timezone || '', cc: j.country || '',
        label: ((j.city ? j.city + ', ' : '') + (j.region || j.country || '')).trim().replace(/,$/, '') || 'Your area',
        accuracy_m: null
      };
    }))
    .then(g => {
      userFix = { lat: g.lat, lon: g.lon, tz: validTz(g.tz) ? g.tz : '' };
      const loc = normalizeLocation({
        lat: g.lat, lon: g.lon, alt: 0, alt_source: 'default',
        tz: g.tz, tz_source: 'provider', cc: g.cc,
        label: g.label, source: 'ip',
        accuracy_m: g.accuracy_m, approx: true
      });
      emit(loc);
      if (config.elevation) refineAltitude(loc);
      return loc;
    });
}

/* ------------------------------------------------------------- altitude --- */

/**
 * Optional DEM elevation refinement. Open-Meteo's elevation endpoint is
 * keyless, CORS open, and serves Copernicus DEM GLO-90 (90 m posting), so the
 * value is a real measurement of the ground, not a guess. At Griffith
 * Observatory it returns 340 m against a surveyed 346 m.
 *
 * Runs AFTER the location is emitted and emits a second update if it lands, so
 * it never blocks a pick. Never overwrites a GPS altitude. On any failure the
 * altitude stays 0 with alt_source "default" - we would rather print an
 * altitude of zero and say so than print an invented number.
 */
export function refineAltitude(loc) {
  const base = loc || current;
  if (!base) return Promise.resolve(null);
  if (base.alt_source === 'gps') return Promise.resolve(base);
  const url = 'https://api.open-meteo.com/v1/elevation?latitude=' + base.lat + '&longitude=' + base.lon;
  return getJSON(url, 5000).then(j => {
    const e = j && Array.isArray(j.elevation) ? Number(j.elevation[0]) : NaN;
    if (!isFinite(e)) return base;
    // Bail if the observer moved while the request was in flight.
    if (!current || current.lat !== base.lat || current.lon !== base.lon) return current;
    if (current.alt_source === 'gps') return current;
    return emit(Object.assign({}, current, { alt: round(e, 1), alt_source: 'dem' }));
  }).catch(() => base);
}

/* ----------------------------------------------------------------- init --- */

/**
 * Boot the location stack.
 *
 * Order of preference:
 *   1. A stored observer from a previous visit - emitted immediately, no
 *      network, no flicker.
 *   2. The configured default (the tzdata New York reference point), emitted
 *      immediately so the app always has a valid observer to render, then
 *      upgraded in place if IP detection succeeds.
 *
 * Options: { autoDetect = true, elevation = true, defaultLocation }.
 * Resolves with the best location available once the first attempt settles.
 */
export function initLocation(options) {
  Object.assign(config, options || {});

  const stored = getStored();
  if (stored) {
    if (stored.from === 'gps' || stored.from === 'ip' || stored.tz_source === 'device') {
      userFix = { lat: stored.lat, lon: stored.lon, tz: stored.tz };
    }
    emit(stored);
    return Promise.resolve(stored);
  }

  const fallbackLoc = normalizeLocation(Object.assign({}, config.defaultLocation, { source: 'default' }));
  emit(fallbackLoc);

  if (!config.autoDetect) return Promise.resolve(fallbackLoc);

  return useIPLocation().catch(() => {
    // Offline or both providers down. The default stands, and it is labelled
    // "default" so the UI can prompt for a real location instead of implying
    // the sunrise shown belongs to the user.
    return current || fallbackLoc;
  });
}

/** Number of tzdata zones in the on-device table. Exposed for diagnostics. */
export const ZONE_COUNT = Object.keys(ZONE_POS).length;

/* ------------------------------------------------------- consumer aliases --
 * sun_map/index.html binds this module by DUCK-TYPING: bindGeo() probes a list
 * of candidate export names and takes the first that is a function.
 *   device/IP chain: ['here','locate','device','deviceLocation', ...]
 *   zone resolver:   ['timezoneFor','tzFor','zoneFor','nearestZone', ...]
 * The canonical names below (useDeviceLocation, zoneForPoint) match NEITHER
 * list, so both seams silently bound to null: the locate button bypassed this
 * module for a bare navigator.geolocation call that dead-ends when GPS is
 * denied, and every remote pick fell back to the DEVICE timezone. These two
 * aliases close that without editing a file this lane does not own. Keep them.
 * Note the probe list puts 'search' AHEAD of 'suggest' - do NOT export a
 * function named `search`, or it would silently displace the debounced
 * suggest() the page currently binds.
 */

/** Alias of useDeviceLocation: GPS first, IP chain on any failure. */
export const locate = useDeviceLocation;

/** Zone id for a point as a plain STRING (the duck-typed consumer feeds the
 *  result straight to a validity check, so an object would be discarded).
 *  Returns null when nothing resolves. Use zoneForPoint when you also want the
 *  basis and the reference distance - which you should, before showing a zone
 *  to a user as if it were looked up. */
export function zoneFor(lat, lon, countryCode) {
  const z = zoneForPoint(lat, lon, countryCode);
  return validTz(z.tz) ? z.tz : null;
}

/* ---------------------------------------- country-constrained zone lookup --
 * Nearest-reference-point alone is wrong wherever a country's reference city
 * is far from the observer. Measured: Tromso (69.65 N, 18.96 E) resolves to
 * Europe/Helsinki, 1090 km away, because Helsinki's reference point is nearer
 * than any Norwegian one. Constraining the candidate set to the country the
 * geocoder reported fixes that whole class of error, and when a country has
 * exactly one zone the answer stops being an inference at all.
 *
 * Country code -> [[zone, lat, lon], ...], from data/zone1970.tab column 1
 * expanded across every listed country. 247 codes, 423 rows. Generated by the
 * same parser as ZONE_POS.
 *
 * NOTE ON THE PARSE, because it bit once already: ISO 6709 signs apply to the
 * WHOLE value, not the degrees alone. Computing -118 + 0.2428 instead of
 * -(118 + 0.2428) puts Los Angeles 45 km east and Honolulu 180 km off, and
 * every negative coordinate on Earth is wrong by up to a degree. If you
 * regenerate this table, spot-check America/Los_Angeles against -118.2428.
 */
const CC_ZONES = {
"AD":[["Europe/Andorra",42.5,1.5167]],"AE":[["Asia/Dubai",25.3,55.3]],"OM":[["Asia/Dubai",25.3,55.3]],
"RE":[["Asia/Dubai",25.3,55.3]],"SC":[["Asia/Dubai",25.3,55.3]],
"TF":[["Asia/Dubai",25.3,55.3],["Indian/Maldives",4.1667,73.5]],"AF":[["Asia/Kabul",34.5167,69.2]],
"AL":[["Europe/Tirane",41.3333,19.8333]],"AM":[["Asia/Yerevan",40.1833,44.5]],
"AQ":[["Antarctica/Casey",-66.2833,110.5167],["Antarctica/Davis",-68.5833,77.9667],["Antarctica/Mawson",-67.6,62.8833],["Antarctica/Palmer",-64.8,-64.1],["Antarctica/Rothera",-67.5667,-68.1333],["Antarctica/Troll",-72.0114,2.535],["Antarctica/Vostok",-78.4,106.9],["Pacific/Auckland",-36.8667,174.7667],["Pacific/Port_Moresby",-9.5,147.1667],["Asia/Riyadh",24.6333,46.7167],["Asia/Singapore",1.2833,103.85]],
"AR":[["America/Argentina/Buenos_Aires",-34.6,-58.45],["America/Argentina/Cordoba",-31.4,-64.1833],["America/Argentina/Salta",-24.7833,-65.4167],["America/Argentina/Jujuy",-24.1833,-65.3],["America/Argentina/Tucuman",-26.8167,-65.2167],["America/Argentina/Catamarca",-28.4667,-65.7833],["America/Argentina/La_Rioja",-29.4333,-66.85],["America/Argentina/San_Juan",-31.5333,-68.5167],["America/Argentina/Mendoza",-32.8833,-68.8167],["America/Argentina/San_Luis",-33.3167,-66.35],["America/Argentina/Rio_Gallegos",-51.6333,-69.2167],["America/Argentina/Ushuaia",-54.8,-68.3]],
"AS":[["Pacific/Pago_Pago",-14.2667,-170.7]],
"UM":[["Pacific/Pago_Pago",-14.2667,-170.7],["Pacific/Tarawa",1.4167,173.0]],
"AT":[["Europe/Vienna",48.2167,16.3333]],
"AU":[["Australia/Lord_Howe",-31.55,159.0833],["Antarctica/Macquarie",-54.5,158.95],["Australia/Hobart",-42.8833,147.3167],["Australia/Melbourne",-37.8167,144.9667],["Australia/Sydney",-33.8667,151.2167],["Australia/Broken_Hill",-31.95,141.45],["Australia/Brisbane",-27.4667,153.0333],["Australia/Lindeman",-20.2667,149.0],["Australia/Adelaide",-34.9167,138.5833],["Australia/Darwin",-12.4667,130.8333],["Australia/Perth",-31.95,115.85],["Australia/Eucla",-31.7167,128.8667],["Asia/Tokyo",35.6544,139.7447]],
"AZ":[["Asia/Baku",40.3833,49.85]],"BB":[["America/Barbados",13.1,-59.6167]],
"BD":[["Asia/Dhaka",23.7167,90.4167]],"BE":[["Europe/Brussels",50.8333,4.3333]],
"LU":[["Europe/Brussels",50.8333,4.3333]],"NL":[["Europe/Brussels",50.8333,4.3333]],
"BG":[["Europe/Sofia",42.6833,23.3167]],"BM":[["Atlantic/Bermuda",32.2833,-64.7667]],
"BO":[["America/La_Paz",-16.5,-68.15]],
"BR":[["America/Noronha",-3.85,-32.4167],["America/Belem",-1.45,-48.4833],["America/Fortaleza",-3.7167,-38.5],["America/Recife",-8.05,-34.9],["America/Araguaina",-7.2,-48.2],["America/Maceio",-9.6667,-35.7167],["America/Bahia",-12.9833,-38.5167],["America/Sao_Paulo",-23.5333,-46.6167],["America/Campo_Grande",-20.45,-54.6167],["America/Cuiaba",-15.5833,-56.0833],["America/Santarem",-2.4333,-54.8667],["America/Porto_Velho",-8.7667,-63.9],["America/Boa_Vista",2.8167,-60.6667],["America/Manaus",-3.1333,-60.0167],["America/Eirunepe",-6.6667,-69.8667],["America/Rio_Branco",-9.9667,-67.8]],
"BT":[["Asia/Thimphu",27.4667,89.65]],"BY":[["Europe/Minsk",53.9,27.5667]],
"BZ":[["America/Belize",17.5,-88.2]],
"CA":[["America/St_Johns",47.5667,-52.7167],["America/Halifax",44.65,-63.6],["America/Glace_Bay",46.2,-59.95],["America/Moncton",46.1,-64.7833],["America/Goose_Bay",53.3333,-60.4167],["America/Toronto",43.65,-79.3833],["America/Iqaluit",63.7333,-68.4667],["America/Winnipeg",49.8833,-97.15],["America/Resolute",74.6956,-94.8292],["America/Rankin_Inlet",62.8167,-92.0831],["America/Regina",50.4,-104.65],["America/Swift_Current",50.2833,-107.8333],["America/Edmonton",53.55,-113.4667],["America/Cambridge_Bay",69.1139,-105.0528],["America/Inuvik",68.3497,-133.7167],["America/Vancouver",49.2667,-123.1167],["America/Dawson_Creek",55.7667,-120.2333],["America/Fort_Nelson",58.8,-122.7],["America/Whitehorse",60.7167,-135.05],["America/Dawson",64.0667,-139.4167],["America/Panama",8.9667,-79.5333],["America/Puerto_Rico",18.4683,-66.1061],["America/Phoenix",33.4483,-112.0733]],
"BS":[["America/Toronto",43.65,-79.3833]],"CH":[["Europe/Zurich",47.3833,8.5333]],
"DE":[["Europe/Zurich",47.3833,8.5333],["Europe/Berlin",52.5,13.3667]],
"LI":[["Europe/Zurich",47.3833,8.5333]],"CI":[["Africa/Abidjan",5.3167,-4.0333]],
"BF":[["Africa/Abidjan",5.3167,-4.0333]],"GH":[["Africa/Abidjan",5.3167,-4.0333]],
"GM":[["Africa/Abidjan",5.3167,-4.0333]],"GN":[["Africa/Abidjan",5.3167,-4.0333]],
"IS":[["Africa/Abidjan",5.3167,-4.0333]],"ML":[["Africa/Abidjan",5.3167,-4.0333]],
"MR":[["Africa/Abidjan",5.3167,-4.0333]],"SH":[["Africa/Abidjan",5.3167,-4.0333]],
"SL":[["Africa/Abidjan",5.3167,-4.0333]],"SN":[["Africa/Abidjan",5.3167,-4.0333]],
"TG":[["Africa/Abidjan",5.3167,-4.0333]],"CK":[["Pacific/Rarotonga",-21.2333,-159.7667]],
"CL":[["America/Santiago",-33.45,-70.6667],["America/Coyhaique",-45.5667,-72.0667],["America/Punta_Arenas",-53.15,-70.9167],["Pacific/Easter",-27.15,-109.4333]],
"CN":[["Asia/Shanghai",31.2333,121.4667],["Asia/Urumqi",43.8,87.5833]],
"CO":[["America/Bogota",4.6,-74.0833]],"CR":[["America/Costa_Rica",9.9333,-84.0833]],
"CU":[["America/Havana",23.1333,-82.3667]],"CV":[["Atlantic/Cape_Verde",14.9167,-23.5167]],
"CY":[["Asia/Nicosia",35.1667,33.3667],["Asia/Famagusta",35.1167,33.95]],
"CZ":[["Europe/Prague",50.0833,14.4333]],"SK":[["Europe/Prague",50.0833,14.4333]],
"DK":[["Europe/Berlin",52.5,13.3667]],"NO":[["Europe/Berlin",52.5,13.3667]],
"SE":[["Europe/Berlin",52.5,13.3667]],"SJ":[["Europe/Berlin",52.5,13.3667]],
"DO":[["America/Santo_Domingo",18.4667,-69.9]],"DZ":[["Africa/Algiers",36.7833,3.05]],
"EC":[["America/Guayaquil",-2.1667,-79.8333],["Pacific/Galapagos",-0.9,-89.6]],
"EE":[["Europe/Tallinn",59.4167,24.75]],"EG":[["Africa/Cairo",30.05,31.25]],
"EH":[["Africa/El_Aaiun",27.15,-13.2]],
"ES":[["Europe/Madrid",40.4,-3.6833],["Africa/Ceuta",35.8833,-5.3167],["Atlantic/Canary",28.1,-15.4]],
"FI":[["Europe/Helsinki",60.1667,24.9667]],"AX":[["Europe/Helsinki",60.1667,24.9667]],
"FJ":[["Pacific/Fiji",-18.1333,178.4167]],"FK":[["Atlantic/Stanley",-51.7,-57.85]],
"FM":[["Pacific/Kosrae",5.3167,162.9833],["Pacific/Port_Moresby",-9.5,147.1667],["Pacific/Guadalcanal",-9.5333,160.2]],
"FO":[["Atlantic/Faroe",62.0167,-6.7667]],"FR":[["Europe/Paris",48.8667,2.3333]],
"MC":[["Europe/Paris",48.8667,2.3333]],"GB":[["Europe/London",51.5083,-0.1253]],
"GG":[["Europe/London",51.5083,-0.1253]],"IM":[["Europe/London",51.5083,-0.1253]],
"JE":[["Europe/London",51.5083,-0.1253]],"GE":[["Asia/Tbilisi",41.7167,44.8167]],
"GF":[["America/Cayenne",4.9333,-52.3333]],"GI":[["Europe/Gibraltar",36.1333,-5.35]],
"GL":[["America/Nuuk",64.1833,-51.7333],["America/Danmarkshavn",76.7667,-18.6667],["America/Scoresbysund",70.4833,-21.9667],["America/Thule",76.5667,-68.7833]],
"GR":[["Europe/Athens",37.9667,23.7167]],"GS":[["Atlantic/South_Georgia",-54.2667,-36.5333]],
"GT":[["America/Guatemala",14.6333,-90.5167]],"GU":[["Pacific/Guam",13.4667,144.75]],
"MP":[["Pacific/Guam",13.4667,144.75]],"GW":[["Africa/Bissau",11.85,-15.5833]],
"GY":[["America/Guyana",6.8,-58.1667]],"HK":[["Asia/Hong_Kong",22.2833,114.15]],
"HN":[["America/Tegucigalpa",14.1,-87.2167]],"HT":[["America/Port-au-Prince",18.5333,-72.3333]],
"HU":[["Europe/Budapest",47.5,19.0833]],
"ID":[["Asia/Jakarta",-6.1667,106.8],["Asia/Pontianak",-0.0333,109.3333],["Asia/Makassar",-5.1167,119.4],["Asia/Jayapura",-2.5333,140.7]],
"IE":[["Europe/Dublin",53.3333,-6.25]],"IL":[["Asia/Jerusalem",31.7806,35.2239]],
"IN":[["Asia/Kolkata",22.5333,88.3667]],"IO":[["Indian/Chagos",-7.3333,72.4167]],
"IQ":[["Asia/Baghdad",33.35,44.4167]],"IR":[["Asia/Tehran",35.6667,51.4333]],
"IT":[["Europe/Rome",41.9,12.4833]],"SM":[["Europe/Rome",41.9,12.4833]],
"VA":[["Europe/Rome",41.9,12.4833]],"JM":[["America/Jamaica",17.9681,-76.7933]],
"JO":[["Asia/Amman",31.95,35.9333]],"JP":[["Asia/Tokyo",35.6544,139.7447]],
"KE":[["Africa/Nairobi",-1.2833,36.8167]],"DJ":[["Africa/Nairobi",-1.2833,36.8167]],
"ER":[["Africa/Nairobi",-1.2833,36.8167]],"ET":[["Africa/Nairobi",-1.2833,36.8167]],
"KM":[["Africa/Nairobi",-1.2833,36.8167]],"MG":[["Africa/Nairobi",-1.2833,36.8167]],
"SO":[["Africa/Nairobi",-1.2833,36.8167]],"TZ":[["Africa/Nairobi",-1.2833,36.8167]],
"UG":[["Africa/Nairobi",-1.2833,36.8167]],"YT":[["Africa/Nairobi",-1.2833,36.8167]],
"KG":[["Asia/Bishkek",42.9,74.6]],
"KI":[["Pacific/Tarawa",1.4167,173.0],["Pacific/Kanton",-2.7833,-171.7167],["Pacific/Kiritimati",1.8667,-157.3333]],
"MH":[["Pacific/Tarawa",1.4167,173.0],["Pacific/Kwajalein",9.0833,167.3333]],
"TV":[["Pacific/Tarawa",1.4167,173.0]],"WF":[["Pacific/Tarawa",1.4167,173.0]],
"KP":[["Asia/Pyongyang",39.0167,125.75]],"KR":[["Asia/Seoul",37.55,126.9667]],
"KZ":[["Asia/Almaty",43.25,76.95],["Asia/Qyzylorda",44.8,65.4667],["Asia/Qostanay",53.2,63.6167],["Asia/Aqtobe",50.2833,57.1667],["Asia/Aqtau",44.5167,50.2667],["Asia/Atyrau",47.1167,51.9333],["Asia/Oral",51.2167,51.35]],
"LB":[["Asia/Beirut",33.8833,35.5]],"LK":[["Asia/Colombo",6.9333,79.85]],
"LR":[["Africa/Monrovia",6.3,-10.7833]],"LT":[["Europe/Vilnius",54.6833,25.3167]],
"LV":[["Europe/Riga",56.95,24.1]],"LY":[["Africa/Tripoli",32.9,13.1833]],
"MA":[["Africa/Casablanca",33.65,-7.5833]],"MD":[["Europe/Chisinau",47.0,28.8333]],
"MM":[["Asia/Yangon",16.7833,96.1667]],"CC":[["Asia/Yangon",16.7833,96.1667]],
"MN":[["Asia/Ulaanbaatar",47.9167,106.8833],["Asia/Hovd",48.0167,91.65]],
"MO":[["Asia/Macau",22.1972,113.5417]],"MQ":[["America/Martinique",14.6,-61.0833]],
"MT":[["Europe/Malta",35.9,14.5167]],"MU":[["Indian/Mauritius",-20.1667,57.5]],
"MV":[["Indian/Maldives",4.1667,73.5]],
"MX":[["America/Mexico_City",19.4,-99.15],["America/Cancun",21.0833,-86.7667],["America/Merida",20.9667,-89.6167],["America/Monterrey",25.6667,-100.3167],["America/Matamoros",25.8333,-97.5],["America/Chihuahua",28.6333,-106.0833],["America/Ciudad_Juarez",31.7333,-106.4833],["America/Ojinaga",29.5667,-104.4167],["America/Mazatlan",23.2167,-106.4167],["America/Bahia_Banderas",20.8,-105.25],["America/Hermosillo",29.0667,-110.9667],["America/Tijuana",32.5333,-117.0167]],
"MY":[["Asia/Kuching",1.55,110.3333],["Asia/Singapore",1.2833,103.85]],
"BN":[["Asia/Kuching",1.55,110.3333]],"MZ":[["Africa/Maputo",-25.9667,32.5833]],
"BI":[["Africa/Maputo",-25.9667,32.5833]],"BW":[["Africa/Maputo",-25.9667,32.5833]],
"CD":[["Africa/Maputo",-25.9667,32.5833],["Africa/Lagos",6.45,3.4]],
"MW":[["Africa/Maputo",-25.9667,32.5833]],"RW":[["Africa/Maputo",-25.9667,32.5833]],
"ZM":[["Africa/Maputo",-25.9667,32.5833]],"ZW":[["Africa/Maputo",-25.9667,32.5833]],
"NA":[["Africa/Windhoek",-22.5667,17.1]],"NC":[["Pacific/Noumea",-22.2667,166.45]],
"NF":[["Pacific/Norfolk",-29.05,167.9667]],"NG":[["Africa/Lagos",6.45,3.4]],
"AO":[["Africa/Lagos",6.45,3.4]],"BJ":[["Africa/Lagos",6.45,3.4]],"CF":[["Africa/Lagos",6.45,3.4]],
"CG":[["Africa/Lagos",6.45,3.4]],"CM":[["Africa/Lagos",6.45,3.4]],"GA":[["Africa/Lagos",6.45,3.4]],
"GQ":[["Africa/Lagos",6.45,3.4]],"NE":[["Africa/Lagos",6.45,3.4]],
"NI":[["America/Managua",12.15,-86.2833]],"NP":[["Asia/Kathmandu",27.7167,85.3167]],
"NR":[["Pacific/Nauru",-0.5167,166.9167]],"NU":[["Pacific/Niue",-19.0167,-169.9167]],
"NZ":[["Pacific/Auckland",-36.8667,174.7667],["Pacific/Chatham",-43.95,-176.55]],
"PA":[["America/Panama",8.9667,-79.5333]],"KY":[["America/Panama",8.9667,-79.5333]],
"PE":[["America/Lima",-12.05,-77.05]],
"PF":[["Pacific/Tahiti",-17.5333,-149.5667],["Pacific/Marquesas",-9.0,-139.5],["Pacific/Gambier",-23.1333,-134.95]],
"PG":[["Pacific/Port_Moresby",-9.5,147.1667],["Pacific/Bougainville",-6.2167,155.5667]],
"PH":[["Asia/Manila",14.5867,120.9678]],"PK":[["Asia/Karachi",24.8667,67.05]],
"PL":[["Europe/Warsaw",52.25,21.0]],"PM":[["America/Miquelon",47.05,-56.3333]],
"PN":[["Pacific/Pitcairn",-25.0667,-130.0833]],"PR":[["America/Puerto_Rico",18.4683,-66.1061]],
"AG":[["America/Puerto_Rico",18.4683,-66.1061]],"AI":[["America/Puerto_Rico",18.4683,-66.1061]],
"AW":[["America/Puerto_Rico",18.4683,-66.1061]],"BL":[["America/Puerto_Rico",18.4683,-66.1061]],
"BQ":[["America/Puerto_Rico",18.4683,-66.1061]],"CW":[["America/Puerto_Rico",18.4683,-66.1061]],
"DM":[["America/Puerto_Rico",18.4683,-66.1061]],"GD":[["America/Puerto_Rico",18.4683,-66.1061]],
"GP":[["America/Puerto_Rico",18.4683,-66.1061]],"KN":[["America/Puerto_Rico",18.4683,-66.1061]],
"LC":[["America/Puerto_Rico",18.4683,-66.1061]],"MF":[["America/Puerto_Rico",18.4683,-66.1061]],
"MS":[["America/Puerto_Rico",18.4683,-66.1061]],"SX":[["America/Puerto_Rico",18.4683,-66.1061]],
"TT":[["America/Puerto_Rico",18.4683,-66.1061]],"VC":[["America/Puerto_Rico",18.4683,-66.1061]],
"VG":[["America/Puerto_Rico",18.4683,-66.1061]],"VI":[["America/Puerto_Rico",18.4683,-66.1061]],
"PS":[["Asia/Gaza",31.5,34.4667],["Asia/Hebron",31.5333,35.095]],
"PT":[["Europe/Lisbon",38.7167,-9.1333],["Atlantic/Madeira",32.6333,-16.9],["Atlantic/Azores",37.7333,-25.6667]],
"PW":[["Pacific/Palau",7.3333,134.4833]],"PY":[["America/Asuncion",-25.2667,-57.6667]],
"QA":[["Asia/Qatar",25.2833,51.5333]],"BH":[["Asia/Qatar",25.2833,51.5333]],
"RO":[["Europe/Bucharest",44.4333,26.1]],"RS":[["Europe/Belgrade",44.8333,20.5]],
"BA":[["Europe/Belgrade",44.8333,20.5]],"HR":[["Europe/Belgrade",44.8333,20.5]],
"ME":[["Europe/Belgrade",44.8333,20.5]],"MK":[["Europe/Belgrade",44.8333,20.5]],
"SI":[["Europe/Belgrade",44.8333,20.5]],
"RU":[["Europe/Kaliningrad",54.7167,20.5],["Europe/Moscow",55.7558,37.6178],["Europe/Simferopol",44.95,34.1],["Europe/Kirov",58.6,49.65],["Europe/Volgograd",48.7333,44.4167],["Europe/Astrakhan",46.35,48.05],["Europe/Saratov",51.5667,46.0333],["Europe/Ulyanovsk",54.3333,48.4],["Europe/Samara",53.2,50.15],["Asia/Yekaterinburg",56.85,60.6],["Asia/Omsk",55.0,73.4],["Asia/Novosibirsk",55.0333,82.9167],["Asia/Barnaul",53.3667,83.75],["Asia/Tomsk",56.5,84.9667],["Asia/Novokuznetsk",53.75,87.1167],["Asia/Krasnoyarsk",56.0167,92.8333],["Asia/Irkutsk",52.2667,104.3333],["Asia/Chita",52.05,113.4667],["Asia/Yakutsk",62.0,129.6667],["Asia/Khandyga",62.6564,135.5539],["Asia/Vladivostok",43.1667,131.9333],["Asia/Ust-Nera",64.5603,143.2267],["Asia/Magadan",59.5667,150.8],["Asia/Sakhalin",46.9667,142.7],["Asia/Srednekolymsk",67.4667,153.7167],["Asia/Kamchatka",53.0167,158.65],["Asia/Anadyr",64.75,177.4833]],
"UA":[["Europe/Simferopol",44.95,34.1],["Europe/Kyiv",50.4333,30.5167]],
"SA":[["Asia/Riyadh",24.6333,46.7167]],"KW":[["Asia/Riyadh",24.6333,46.7167]],
"YE":[["Asia/Riyadh",24.6333,46.7167]],"SB":[["Pacific/Guadalcanal",-9.5333,160.2]],
"SD":[["Africa/Khartoum",15.6,32.5333]],"SG":[["Asia/Singapore",1.2833,103.85]],
"SR":[["America/Paramaribo",5.8333,-55.1667]],"SS":[["Africa/Juba",4.85,31.6167]],
"ST":[["Africa/Sao_Tome",0.3333,6.7333]],"SV":[["America/El_Salvador",13.7,-89.2]],
"SY":[["Asia/Damascus",33.5,36.3]],"TC":[["America/Grand_Turk",21.4667,-71.1333]],
"TD":[["Africa/Ndjamena",12.1167,15.05]],"TH":[["Asia/Bangkok",13.75,100.5167]],
"CX":[["Asia/Bangkok",13.75,100.5167]],"KH":[["Asia/Bangkok",13.75,100.5167]],
"LA":[["Asia/Bangkok",13.75,100.5167]],
"VN":[["Asia/Bangkok",13.75,100.5167],["Asia/Ho_Chi_Minh",10.75,106.6667]],
"TJ":[["Asia/Dushanbe",38.5833,68.8]],"TK":[["Pacific/Fakaofo",-9.3667,-171.2333]],
"TL":[["Asia/Dili",-8.55,125.5833]],"TM":[["Asia/Ashgabat",37.95,58.3833]],
"TN":[["Africa/Tunis",36.8,10.1833]],"TO":[["Pacific/Tongatapu",-21.1333,-175.2]],
"TR":[["Europe/Istanbul",41.0167,28.9667]],"TW":[["Asia/Taipei",25.05,121.5]],
"US":[["America/New_York",40.7142,-74.0064],["America/Detroit",42.3314,-83.0458],["America/Kentucky/Louisville",38.2542,-85.7594],["America/Kentucky/Monticello",36.8297,-84.8492],["America/Indiana/Indianapolis",39.7683,-86.1581],["America/Indiana/Vincennes",38.6772,-87.5286],["America/Indiana/Winamac",41.0514,-86.6031],["America/Indiana/Marengo",38.3756,-86.3447],["America/Indiana/Petersburg",38.4919,-87.2786],["America/Indiana/Vevay",38.7478,-85.0672],["America/Chicago",41.85,-87.65],["America/Indiana/Tell_City",37.9531,-86.7614],["America/Indiana/Knox",41.2958,-86.625],["America/Menominee",45.1078,-87.6142],["America/North_Dakota/Center",47.1164,-101.2992],["America/North_Dakota/New_Salem",46.845,-101.4108],["America/North_Dakota/Beulah",47.2642,-101.7778],["America/Denver",39.7392,-104.9842],["America/Boise",43.6136,-116.2025],["America/Phoenix",33.4483,-112.0733],["America/Los_Angeles",34.0522,-118.2428],["America/Anchorage",61.2181,-149.9003],["America/Juneau",58.3019,-134.4197],["America/Sitka",57.1764,-135.3019],["America/Metlakatla",55.1269,-131.5764],["America/Yakutat",59.5469,-139.7272],["America/Nome",64.5011,-165.4064],["America/Adak",51.88,-176.6581],["Pacific/Honolulu",21.3069,-157.8583]],
"UY":[["America/Montevideo",-34.9092,-56.2125]],
"UZ":[["Asia/Samarkand",39.6667,66.8],["Asia/Tashkent",41.3333,69.3]],
"VE":[["America/Caracas",10.5,-66.9333]],"VU":[["Pacific/Efate",-17.6667,168.4167]],
"WS":[["Pacific/Apia",-13.8333,-171.7333]],"ZA":[["Africa/Johannesburg",-26.25,28.0]],
"LS":[["Africa/Johannesburg",-26.25,28.0]],"SZ":[["Africa/Johannesburg",-26.25,28.0]]
};

/**
 * Best zone for a point, given the country the geocoder reported.
 * Returns { tz, km, basis } where basis is:
 *   "country"         the country has exactly one zone - not a guess
 *   "country+nearest" nearest reference point WITHIN the right country
 *   "nearest"         no country known, global nearest, weakest case
 */
export function zoneForPoint(lat, lon, countryCode) {
  const pool = CC_ZONES[String(countryCode || '').toUpperCase()];
  // km is null, not 0, when the country decides it: no reference point was
  // consulted, so there is no distance to report. Reporting 0 would be a
  // measurement we never took - Norway resolves to Europe/Berlin correctly,
  // and Berlin's reference point is about 2000 km from Tromso.
  if (pool && pool.length === 1) return { tz: pool[0][0], km: null, basis: 'country' };
  if (pool && pool.length > 1) {
    let best = null, bestKm = Infinity;
    for (const row of pool) {
      const km = distKm(lat, lon, row[1], row[2]);
      if (km < bestKm) { bestKm = km; best = row[0]; }
    }
    return { tz: best, km: Math.round(bestKm * 10) / 10, basis: 'country+nearest' };
  }
  const n = nearestTimeZone(lat, lon);
  return { tz: n.tz, km: n.km, basis: 'nearest' };
}
