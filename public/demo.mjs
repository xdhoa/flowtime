import {DEFAULT_SETTINGS} from './planner.mjs';
const KEY='flowtime-v2-demo';const uid=()=>crypto.randomUUID();const iso=(days,hour=17)=>{const d=new Date();d.setDate(d.getDate()+days);d.setHours(hour,0,0,0);return d.toISOString()};
export function seed(){let user={id:'demo-manager',email:'manager@example.com',name:'Ngọc Hòa',manager:true},requester={id:'demo-requester',email:'requester@example.com',name:'Minh Anh',manager:false};const samples=[['Hoàn thiện proposal hợp tác','Proposal & kế hoạch','accepted',1,150,3],['Chuẩn bị nội dung truyền thông sự kiện','Truyền thông','doing',2,90,2],['Tổng hợp hồ sơ đối tác','Nghiên cứu','waiting',3,120,2],['Thiết kế agenda buổi làm việc','Sự kiện','new',4,60,1],['Bàn giao báo cáo hoạt động tháng','Báo cáo','review',0,180,2]];let tasks=samples.map((x,i)=>({id:uid(),requester_id:requester.id,requester_email:requester.email,requester_name:requester.name,title:x[0],description:'Chuẩn bị bản hoàn chỉnh để các bên xem xét. Cần xác nhận nội dung chính trước khi bàn giao.',deliverable:'Tài liệu hoàn chỉnh và đường dẫn bản chỉnh sửa.',category:x[1],collaborators:i%2?'Phòng Truyền thông':'Nhóm Đối ngoại',requested_deadline:iso(x[3]),committed_deadline:x[2]==='new'?null:iso(x[3]),status:x[2],attachment_url:'',result:x[2]==='review'?'Đã hoàn thành bản báo cáo. Vui lòng bổ sung đường dẫn tài liệu tại đây.':'',created_at:iso(-3,9),updated_at:new Date().toISOString()}));return {user,requester,tasks,plans:tasks.filter(t=>t.status!=='new').map(t=>({task_id:t.id,estimate_minutes:samples.find(x=>x[0]===t.title)[4],priority:samples.find(x=>x[0]===t.title)[5],private_notes:'',ai_estimate:null})),sessions:[{id:uid(),manager_id:user.id,task_id:tasks[1].id,started_at:new Date(Date.now()-22*60000).toISOString(),ended_at:null},{id:uid(),manager_id:user.id,task_id:tasks[4].id,started_at:iso(-1,9),ended_at:iso(-1,11)}],events:tasks.map(t=>({id:uid(),task_id:t.id,actor_id:requester.id,actor_name:requester.name,body:'Đã gửi yêu cầu mới.',created_at:t.created_at})),settings:structuredClone(DEFAULT_SETTINGS)}}
let state;export function loadDemo(){try{state=JSON.parse(localStorage.getItem(KEY))||seed()}catch{state=seed()}return state}
export function resetDemo(){state=seed();persist()};function persist(){localStorage.setItem(KEY,JSON.stringify(state))}
export async function demoAPI(path,body,manager=true){if(!state)loadDemo();let user=manager?state.user:state.requester;let bits=path.split('/'),task=state.tasks.find(t=>t.id===bits[1]),action=bits[2];const ev=body=>state.events.push({id:uid(),task_id:task.id,actor_id:user.id,actor_name:user.name,body,created_at:new Date().toISOString()});function stop(id){state.sessions.filter(s=>!s.ended_at&&(!id||s.task_id===id)).forEach(s=>s.ended_at=new Date().toISOString())}
if(path==='profile'){if(!/^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/.test(body?.slug||''))throw Error('Mã chỉ gồm chữ thường không dấu, số và dấu gạch ngang (3–40 ký tự).');state.user.slug=body.slug;persist();return {ok:true,slug:body.slug}}
if(path==='data')return structuredClone({user,manager:manager?{slug:state.user.slug||'demo',name:state.user.name}:null,tasks:manager?state.tasks:state.tasks.filter(t=>t.requester_id===user.id),plans:manager?state.plans:[],sessions:manager?state.sessions:[],settings:state.settings});
if(path==='ai')throw Error('La bàn AI chưa được kết nối trong demo. Cấu hình OPENAI_API_KEY để dùng AI thật.');
if(path==='settings'){state.settings=body;persist();return {ok:true}};
if(path==='tasks'){task={...body,id:uid(),requester_id:user.id,requester_name:user.name,requester_email:user.email,status:'new',committed_deadline:null,result:'',created_at:new Date().toISOString(),updated_at:new Date().toISOString()};state.tasks.unshift(task);ev('Đã gửi yêu cầu mới.');persist();return {task}}
if(!task)throw Error('Không tìm thấy công việc demo.');
if(action==='events')return {events:structuredClone(state.events.filter(e=>e.task_id===task.id))};
if(action==='comment')ev(body.body);
if(action==='plan'){state.plans=state.plans.filter(p=>p.task_id!==task.id);state.plans.push({...body,task_id:task.id});task.committed_deadline=body.committed_deadline;if(task.status==='new')task.status='accepted';ev('Đã xác nhận kế hoạch và thời hạn bàn giao.');}
if(action==='timer'){if(body.action==='start'){stop();state.tasks.filter(t=>t.status==='doing').forEach(t=>t.status='accepted');task.status='doing';state.sessions.push({id:uid(),manager_id:state.user.id,task_id:task.id,started_at:new Date().toISOString(),ended_at:null})}else stop(task.id)}
if(action==='status'){stop(task.id);task.status=body.status;task.result=body.result??task.result;ev('Đã cập nhật trạng thái công việc.');}
if(action==='accept'){task.status='delivered';ev('Đã xác nhận kết quả và hoàn tất bàn giao.');}
if(action==='decline'){if(['delivered','declined'].includes(task.status))throw Error('Không thể từ chối việc đã bàn giao hoặc đã từ chối.');if(!body?.reason?.trim())throw Error('Hãy nhập lý do từ chối.');stop(task.id);task.status='declined';ev('Đã từ chối yêu cầu. Lý do: '+body.reason.trim());}
if(action==='reopen'){if(task.status!=='declined')throw Error('Chỉ mở lại được yêu cầu đã từ chối.');task.status='new';ev('Đã mở lại yêu cầu để xem xét.');}
if(action==='handoff')throw Error('Demo không gửi email. Bạn có thể sao chép nội dung bàn giao.');task.updated_at=new Date().toISOString();persist();return {ok:true}}

// Demo version of the no-sign-in request flow (public/* routes). Requests land in the same
// browser-only demo data, so the demo manager dashboard sees them.
export async function demoGuestAPI(path, body = {}) {
  if (!state) loadDemo();
  state.guestTokens ??= {};
  const now = new Date().toISOString();
  if (path === 'public/ai') throw Error('AI chưa được kết nối trong demo. Hãy điền biểu mẫu trực tiếp.');
  const slug = state.user.slug || 'demo';
  const noManager = 'Không tìm thấy người quản lý với mã này. Trong demo, hãy dùng mã: ' + slug;
  if (path === 'public/manager') {
    if ((body.slug || '').trim().toLowerCase() !== slug) throw Error(noManager);
    return {slug, name: state.user.name};
  }
  if (path === 'public/tasks') {
    if ((body.manager || '').trim().toLowerCase() !== slug) throw Error(noManager);
    const token = (uid() + uid()).replaceAll('-', '');
    const task = {id: uid(), requester_id: null, requester_name: body.name, requester_email: body.email, title: body.title,
      description: body.description || '', deliverable: body.deliverable || '', category: body.category || 'Khác',
      collaborators: body.collaborators || '', attachment_url: body.attachment_url || '', requested_deadline: body.requested_deadline,
      committed_deadline: null, status: 'new', result: '', created_at: now, updated_at: now};
    state.tasks.unshift(task);
    state.guestTokens[token] = task.id;
    state.events.push({id: uid(), task_id: task.id, actor_id: null, actor_name: body.name, body: 'Đã gửi yêu cầu mới (không đăng nhập).', created_at: now});
    persist();
    return {task: {id: task.id, title: task.title}, token, manager: state.user.name};
  }
  const task = state.tasks.find(t => t.id === state.guestTokens[body.token]);
  if (!task) throw Error('Đường dẫn theo dõi không hợp lệ hoặc đã hết hiệu lực.');
  const ev = text => state.events.push({id: uid(), task_id: task.id, actor_id: null, actor_name: task.requester_name, body: text, created_at: new Date().toISOString()});
  if (path === 'public/track') return structuredClone({task, events: state.events.filter(e => e.task_id === task.id)});
  if (path === 'public/comment') ev(body.body);
  else if (path === 'public/accept') {
    if (task.status !== 'review') throw Error('Chỉ duyệt được kết quả đang chờ duyệt.');
    task.status = 'delivered';
    ev('Đã xác nhận kết quả và hoàn tất bàn giao.');
  } else throw Error('Không tìm thấy thao tác demo.');
  task.updated_at = now;
  persist();
  return {ok: true};
}
