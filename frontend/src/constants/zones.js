// 常用 IANA 时区，值与后端 zoneinfo 名称一致。
export const TIMEZONES=[
 ['Asia/Shanghai','中国 · 上海 (UTC+8)'],
 ['Asia/Bangkok','泰国 · 曼谷 (UTC+7)'],
 ['Asia/Singapore','新加坡 (UTC+8)'],
 ['Asia/Tokyo','日本 · 东京 (UTC+9)'],
 ['Asia/Dubai','阿联酋 · 迪拜 (UTC+4)'],
 ['Europe/Berlin','德国 · 柏林 (中欧时间)'],
 ['Europe/London','英国 · 伦敦 (格林尼治)'],
 ['Europe/Paris','法国 · 巴黎 (中欧时间)'],
 ['America/New_York','美国 · 纽约 (东部时间)'],
 ['America/Chicago','美国 · 芝加哥 (中部时间)'],
 ['America/Los_Angeles','美国 · 洛杉矶 (太平洋时间)'],
 ['America/Sao_Paulo','巴西 · 圣保罗'],
 ['Australia/Sydney','澳大利亚 · 悉尼'],
 ['UTC','协调世界时 UTC'],
];
export const WORKDAYS=[['mon','周一'],['tue','周二'],['wed','周三'],['thu','周四'],['fri','周五'],['sat','周六'],['sun','周日']];
export const WEEKDAY_LABEL=Object.fromEntries(WORKDAYS);
// 浏览器选择的本地时间 → UTC unix 秒（班历调整生效时间口径为 UTC）
export function localInputToUtc(value){
 if(!value)return null;
 const t=new Date(value);
 if(Number.isNaN(t.getTime()))return null;
 return Math.floor(t.getTime()/1000);
}
export function utcToLocalInput(ts){
 if(ts==null)return '';
 const d=new Date(ts*1000),p=n=>String(n).padStart(2,'0');
 return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function todayInput(){return utcToLocalInput(Date.now()/1000).slice(0,10);}
