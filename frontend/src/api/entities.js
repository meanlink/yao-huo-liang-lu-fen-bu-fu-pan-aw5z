import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={
 list:()=>api('/reports'),
 create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),
 toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),
 preview:data=>api('/reports/preview',{method:'POST',body:JSON.stringify(data)}),
 adjust:(id,data)=>api('/reports/'+id+'/adjust',{method:'POST',body:JSON.stringify(data)}),
 versions:id=>api('/reports/'+id+'/versions'),
 slots:(id,status='')=>api('/reports/'+id+'/slots'+(status?('?status='+status):'')),
 deliveries:(reportId='')=>api('/deliveries'+(reportId?('?report_id='+reportId):'')),
};
