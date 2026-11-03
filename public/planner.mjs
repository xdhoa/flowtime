export const STATUSES={new:'Mới gửi',accepted:'Đã tiếp nhận',doing:'Đang làm',waiting:'Chờ phối hợp',review:'Chờ duyệt',delivered:'Đã bàn giao'};
export const DEFAULT_SETTINGS={timezone:'Asia/Ho_Chi_Minh',weekdays:[1,2,3,4,5],start:9,end:18,lunchStart:12,lunchEnd:13,buffer:15,busy:[]};
export function actualMinutes(id,sessions,now=Date.now()) {return sessions.filter(s=>s.task_id===id).reduce((n,s)=>n+Math.max(0,((s.ended_at?Date.parse(s.ended_at):now)-Date.parse(s.started_at))/60000),0)}
const formatters=new Map();
export function localParts(time,timezone) {if(!formatters.has(timezone))formatters.set(timezone,new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}));const p=Object.fromEntries(formatters.get(timezone).formatToParts(new Date(time)).map(x=>[x.type,x.value]));return {day:`${p.year}-${p.month}-${p.day}`,weekday:new Date(`${p.year}-${p.month}-${p.day}T12:00:00Z`).getUTCDay(),minute:Number(p.hour)*60+Number(p.minute)}}
export function available(time,settings) {let p=localParts(time,settings.timezone);return settings.weekdays.includes(p.weekday)&&p.minute>=settings.start*60&&p.minute<settings.end*60&&!(p.minute>=settings.lunchStart*60&&p.minute<settings.lunchEnd*60)&&!settings.busy.some(b=>time>=Date.parse(b.start)&&time<Date.parse(b.end))}
// Quarter-hour slots; capacity respects working days, lunch, busy periods and buffer.
// The planner is deterministic; AI cannot silently move accepted deadlines.
export function schedule(tasks,plans,sessions,settings=DEFAULT_SETTINGS,now=Date.now()) {
 let cursor=Math.ceil(now/900000)*900000;const horizon=cursor+90*86400000;
 const queue=tasks.filter(t=>['accepted','doing'].includes(t.status)).map(t=>({t,p:plans.find(p=>p.task_id===t.id)})).filter(x=>x.p).sort((a,b)=>(a.t.status==='doing'?-1:0)-(b.t.status==='doing'?-1:0)||(b.p.priority-a.p.priority)||Date.parse(a.t.committed_deadline||a.t.requested_deadline)-Date.parse(b.t.committed_deadline||b.t.requested_deadline));
 return queue.map(({t,p})=>{let remaining=Math.max(0,p.estimate_minutes-actualMinutes(t.id,sessions,now));let needed=remaining+(remaining>0?settings.buffer:0),segments=[],first=null;
 while(needed>0&&cursor<horizon){let used=Math.min(15,needed);const slotEnd=cursor+used*60000;if(available(cursor,settings)&&available(slotEnd-1,settings)&&!settings.busy.some(b=>cursor<Date.parse(b.end)&&slotEnd>Date.parse(b.start))){if(!first)first=cursor;let prev=segments.at(-1);if(prev&&prev.end===cursor)prev.end=cursor+used*60000;else segments.push({start:cursor,end:cursor+used*60000});needed-=used}cursor+=900000}
 let finish=segments.at(-1)?.end||now;return {task:t,remaining,start:first,end:finish,segments,unscheduled:needed>0,risk:needed>0||finish>Date.parse(t.committed_deadline||t.requested_deadline)}
 })
}
export const duration=m=>m>=60?`${Math.floor(m/60)}g ${Math.round(m%60)}p`:`${Math.round(m)} phút`;
