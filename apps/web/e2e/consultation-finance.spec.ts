import {test,expect} from '@playwright/test';
test('Reception bills, recovers an interrupted collection, prints receipts and uses a free follow-up',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.NEXT_PUBLIC_API_URL||'http://127.0.0.1:8000/api/v1';
 const login=async(username:string,password:string)=>{const r=await request.post(base+'/auth/login',{data:{username,password}});expect(r.ok()).toBeTruthy();return {Authorization:'Bearer '+(await r.json()).access_token}};
 const admin=await login(process.env.STAFF_ADMIN_USERNAME||'admin',process.env.STAFF_ADMIN_PASSWORD||'Browser!Admin2026');
 const meta=await (await request.get(base+'/meta/bootstrap',{headers:admin})).json();
 const branch=meta.branches.find((x:any)=>x.name==='Paloura'),doctor=meta.doctors[0],service=meta.services.find((x:any)=>x.code==='CONSULT');
 const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 expect((await request.post(base+'/consultation-finance/fees',{headers:admin,data:{service_id:service.id,branch_id:branch.id,doctor_id:doctor.id,amount:'500.00',effective_from:day}})).ok()).toBeTruthy();
 expect((await request.post(base+'/consultation-finance/policies',{headers:admin,data:{name:'Browser ten-day policy',free_followup_window_days:10,max_free_followups:1,effective_from:day}})).ok()).toBeTruthy();
 const username='finance'+Date.now(),temp='Finance!Temp2026',password='Finance!Private2026';
 expect((await request.post(base+'/admin/staff',{headers:admin,data:{name:'Fictional Finance Reception',username,role:'RECEPTIONIST',branch_ids:[branch.id],temporary_password:temp}})).ok()).toBeTruthy();
 const first=await login(username,temp);expect((await request.post(base+'/auth/change-password',{headers:first,data:{current_password:temp,new_password:password}})).ok()).toBeTruthy();
 const reception=await login(username,password);
 const name='Fictional Finance '+Date.now();
 const pr=await request.post(base+'/patients',{headers:reception,data:{organization_id:meta.organization_id,registration_branch_id:branch.id,full_name:name,age_years:40,gender:'Female',identity_verified:true,registration_request_id:crypto.randomUUID()}});expect(pr.ok()).toBeTruthy();const patient=await pr.json();
 async function visit(){const r=await request.post(base+'/visits',{headers:reception,data:{patient_id:patient.patient_id,patient_row_version:patient.row_version,creation_request_id:crypto.randomUUID(),branch_id:branch.id,doctor_id:doctor.id,visit_type_id:meta.visit_types.find((x:any)=>x.code==='CONSULTATION').id,identity_confirmed:true}});expect(r.ok()).toBeTruthy();return r.json()}
 const v=await visit();
 await page.goto('/login');await page.getByLabel('Username',{exact:true}).fill(username);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Sign in',exact:true}).click();await page.getByRole('link',{name:'Consultation Finance',exact:true}).click();
 const row=page.getByRole('region',{name:'Finance '+name,exact:true});await expect(row).toContainText('Payment required');
 await expect(row.getByRole('button',{name:'Create Bill',exact:true})).toBeDisabled();await row.getByRole('checkbox').check();await row.getByRole('button',{name:'Create Bill',exact:true}).click();
 await expect(row).toContainText('Draft bill');await row.getByRole('checkbox').check();await row.getByRole('button',{name:'Finalize Bill',exact:true}).click();await expect(row).toContainText('Awaiting payment');
 await row.getByRole('checkbox').check();await row.getByLabel('Payment mode '+v.visit_id,{exact:true}).selectOption({label:'Cash'});await row.getByLabel('Payment amount '+v.visit_id,{exact:true}).fill('200');
 let interrupted=false;
 await page.route('**/consultation-finance/payments',async route=>{if(!interrupted&&route.request().method()==='POST'){interrupted=true;const response=await route.fetch();expect(response.ok()).toBeTruthy();await route.abort('failed')}else await route.continue()});
 await row.getByRole('button',{name:'Receive Payment',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'Recover Payment'})).toContainText('Recover Payment');
 await page.reload();await expect(row.getByRole('button',{name:'Recover Payment',exact:true})).toBeVisible();await row.getByRole('button',{name:'Recover Payment',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Payment saved. Receipt:');await expect(row.getByRole('link',{name:'Print Receipt',exact:true})).toHaveCount(1);
 await row.getByRole('checkbox').check();await row.getByLabel('Payment mode '+v.visit_id,{exact:true}).selectOption({label:'Upi'});await row.getByLabel('Payment amount '+v.visit_id,{exact:true}).fill('300');await row.getByRole('button',{name:'Receive Payment',exact:true}).click();
 await expect(row).toContainText('Cleared');await expect(row.getByRole('link',{name:'Print Receipt',exact:true})).toHaveCount(2);
 const popup=page.waitForEvent('popup');await row.getByRole('link',{name:'Print Receipt',exact:true}).last().click();const receipt=await popup;await expect(receipt.getByRole('heading',{name:'Payment Receipt',exact:true})).toBeVisible();await expect(receipt.getByText(patient.uhid,{exact:true})).toBeVisible();await receipt.close();
 const billPopup=page.waitForEvent('popup');await row.getByRole('link',{name:'Print Bill',exact:true}).click();const bill=await billPopup;await expect(bill.getByRole('heading',{name:'Consultation Bill',exact:true})).toBeVisible();await bill.close();
 // New encounter after qualifying payment uses the Patient-level entitlement.
 const follow=await visit();await page.goto('/finance?visit='+follow.visit_id);await expect(row).toContainText('Free follow-up available');await row.getByRole('checkbox').check();await row.getByRole('button',{name:'Use Free Follow-Up',exact:true}).click();await expect(row).toContainText('FREE FOLLOWUP');
 await page.setViewportSize({width:390,height:844});await expect(row).toBeVisible();expect(errors).toEqual([]);
});
