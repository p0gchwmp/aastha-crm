import {test,expect} from '@playwright/test';
test.afterEach(async({page},info)=>{if(info.status!==info.expectedStatus)console.log('Doctor test screen:',await page.locator('body').innerText())});
test('Doctor starts, safely retries notes, completes consultation and preserves Patient history',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.NEXT_PUBLIC_API_URL||'http://127.0.0.1:8000/api/v1';
 const login=async(username:string,password:string)=>{const r=await request.post(base+'/auth/login',{data:{username,password}});expect(r.ok()).toBeTruthy();return {Authorization:'Bearer '+(await r.json()).access_token}};
 const admin=await login(process.env.STAFF_ADMIN_USERNAME||'admin',process.env.STAFF_ADMIN_PASSWORD||'Browser!Admin2026');
 const meta=await (await request.get(base+'/meta/bootstrap',{headers:admin})).json();
 const branch=meta.branches.find((x:any)=>x.name==='Paloura'),doctor=meta.doctors[0];
 const name='Fictional Doctor '+Date.now();
 const r=await request.post(base+'/patients',{headers:admin,data:{organization_id:meta.organization_id,registration_branch_id:branch.id,full_name:name,age_years:40,gender:'Female',identity_verified:true,registration_request_id:crypto.randomUUID()}});expect(r.ok()).toBeTruthy();const patient=await r.json();
 async function visit(){const r=await request.post(base+'/visits',{headers:admin,data:{patient_id:patient.patient_id,patient_row_version:patient.row_version,creation_request_id:crypto.randomUUID(),branch_id:branch.id,doctor_id:doctor.id,visit_type_id:meta.visit_types.find((x:any)=>x.code==='CONSULTATION').id,identity_confirmed:true}});expect(r.ok()).toBeTruthy();return r.json()}
 const v=await visit();
 await page.goto('/login');await page.getByLabel('Username',{exact:true}).fill('doctor');await page.getByLabel('Password',{exact:true}).fill('Browser!Doctor2026');await page.getByRole('button',{name:'Sign in',exact:true}).click();await page.getByRole('link',{name:'Doctor Consultations',exact:true}).click();
 await page.getByRole('button',{name:'Open '+name,exact:true}).click();const current=page.getByRole('region',{name:'Current consultation'});
 await expect(current.getByRole('button',{name:'Start Consultation',exact:true})).toBeDisabled();await current.getByRole('checkbox').check();await current.getByRole('button',{name:'Start Consultation',exact:true}).click();await expect(current).toContainText('IN PROGRESS');
 await current.getByLabel('History',{exact:true}).fill('Fictional clinical history');await current.getByLabel('Assessment',{exact:true}).fill('Fictional assessment');await current.getByLabel('Treatment plan',{exact:true}).fill('Fictional treatment plan');await current.getByLabel('Follow-up advice',{exact:true}).fill('Fictional follow-up advice');await current.getByLabel('Follow-up date',{exact:true}).fill('2030-01-15');
 let interrupted=false;await page.route('**/doctor-consultations/*/save',async route=>{if(!interrupted){interrupted=true;const r=await route.fetch();expect(r.ok()).toBeTruthy();await route.abort('failed')}else await route.continue()});
 await current.getByRole('button',{name:'Save Notes',exact:true}).click();await current.getByRole('button',{name:'Retry Save',exact:true}).click();await expect(page.getByRole('status')).toContainText('saved successfully');
 await page.reload();await page.getByRole('button',{name:'Open '+name,exact:true}).click();await expect(current.getByLabel('History',{exact:true})).toHaveValue('Fictional clinical history');
 page.once('dialog',d=>d.accept());await current.getByRole('button',{name:'Complete Consultation',exact:true}).click();await expect(current).toContainText('COMPLETED');await expect(current.getByLabel('History',{exact:true})).toBeDisabled();await expect(current.locator('summary')).toHaveText('Saved versions (3)');
 const second=await visit();await page.getByRole('button',{name:'Refresh waiting list',exact:true}).click();const opened=page.getByRole('button',{name:'Open '+name,exact:true});await opened.last().click();await expect(current).toContainText('Fictional clinical history');
 const status=await request.get(base+'/visits/'+v.visit_id,{headers:admin});expect((await status.json()).status_code).toBe('COMPLETED');expect(await status.text()).not.toContain('Fictional clinical history');
 expect(second.visit_id).not.toBe(v.visit_id);expect(errors).toEqual([]);
});
