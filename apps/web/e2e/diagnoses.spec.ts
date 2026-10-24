import {test,expect} from '@playwright/test';
test('Doctor selects multiple diagnoses; catalogue edits preserve recorded clinical history',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.NEXT_PUBLIC_API_URL||'http://127.0.0.1:8000/api/v1';
 const login=async(username:string,password:string)=>{const r=await request.post(base+'/auth/login',{data:{username,password}});expect(r.ok()).toBeTruthy();return {Authorization:'Bearer '+(await r.json()).access_token}};
 const admin=await login(process.env.STAFF_ADMIN_USERNAME||'admin',process.env.STAFF_ADMIN_PASSWORD||'Browser!Admin2026');
 const meta=await(await request.get(base+'/meta/bootstrap',{headers:admin})).json();
 const branch=meta.branches.find((x:any)=>x.name==='Paloura'),doctor=meta.doctors.find((x:any)=>x.name==='Dr. Cheena Langer');
 const stamp=Date.now(),name='Fictional Diagnosis Patient '+stamp,a='Fictional Diagnosis A '+stamp,b='Fictional Diagnosis B '+stamp;
 let r=await request.post(base+'/patients',{headers:admin,data:{organization_id:meta.organization_id,registration_branch_id:branch.id,full_name:name,age_years:42,gender:'Female',identity_verified:true,registration_request_id:crypto.randomUUID()}});expect(r.ok()).toBeTruthy();const patient=await r.json();
 r=await request.post(base+'/visits',{headers:admin,data:{patient_id:patient.patient_id,patient_row_version:patient.row_version,creation_request_id:crypto.randomUUID(),branch_id:branch.id,doctor_id:doctor.id,visit_type_id:meta.visit_types.find((x:any)=>x.code==='CONSULTATION').id,identity_confirmed:true}});expect(r.ok()).toBeTruthy();const v=await r.json();
 await page.goto('/login');await page.getByLabel('Username',{exact:true}).fill('doctor');await page.getByLabel('Password',{exact:true}).fill('Browser!Doctor2026');await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('link',{name:'Diagnosis Master',exact:true}).click();
 for(const diagnosis of [a,b]){await page.getByRole('button',{name:'New diagnosis',exact:true}).click();await page.getByLabel('Diagnosis name',{exact:true}).fill(diagnosis);await page.getByLabel('Category',{exact:true}).fill('Browser test');await page.getByRole('button',{name:'Save diagnosis',exact:true}).click();await expect(page.getByRole('status')).toContainText('Diagnosis saved successfully')}
 await page.getByRole('link',{name:'Doctor Consultations',exact:true}).click();await page.getByRole('button',{name:'Open '+name,exact:true}).click();const current=page.getByRole('region',{name:'Current consultation',exact:true});
 await current.getByRole('checkbox').check();await current.getByRole('button',{name:'Start Consultation',exact:true}).click();await expect(current).toContainText('IN PROGRESS');
 const diagnoses=current.getByRole('region',{name:'Visit diagnoses',exact:true});
 await expect(diagnoses.getByRole('button',{name:/^Add /})).toHaveCount(0);
 await diagnoses.getByLabel('Search diagnoses',{exact:true}).fill('a');
 await expect(diagnoses.getByRole('button',{name:/^Add /})).toHaveCount(0);
 for(const diagnosis of [a,b]){await diagnoses.getByLabel('Search diagnoses',{exact:true}).fill(diagnosis);await diagnoses.getByRole('button',{name:'Add '+diagnosis,exact:true}).click();await expect(diagnoses.getByLabel('Search diagnoses',{exact:true})).toHaveValue('');await expect(diagnoses.getByRole('button',{name:/^Add /})).toHaveCount(0)}
 await diagnoses.getByRole('radio',{name:'Primary diagnosis '+b,exact:true}).check();
 const radio=diagnoses.getByRole('radio',{name:'Primary diagnosis '+b,exact:true});
 const box=await radio.boundingBox();expect(box!.width).toBeLessThan(24);
 const primaryLabel=await radio.locator('..').boundingBox();expect(primaryLabel!.width).toBeLessThan(120);
 await diagnoses.getByLabel('Search diagnoses',{exact:true}).fill('ac');
 await expect(diagnoses.getByRole('button',{name:/^Add /}).first()).toBeVisible();
 expect(await diagnoses.getByRole('button',{name:/^Add /}).count()).toBeLessThanOrEqual(10);
 await diagnoses.getByLabel('Search diagnoses',{exact:true}).press('Escape');
 await expect(diagnoses.getByRole('button',{name:/^Add /})).toHaveCount(0);
 // A network failure after commit must safely replay the same diagnosis selection.
 let interrupted=false;await page.route('**/doctor-consultations/*/save',async route=>{if(!interrupted){interrupted=true;const reply=await route.fetch();expect(reply.ok()).toBeTruthy();await route.abort('failed')}else await route.continue()});
 await current.getByRole('button',{name:'Save Notes',exact:true}).click();await current.getByRole('button',{name:'Retry Save',exact:true}).click();await expect(page.getByRole('status')).toContainText('saved successfully');
 await page.reload();await page.getByRole('button',{name:'Open '+name,exact:true}).click();await expect(diagnoses.getByRole('radio',{name:'Primary diagnosis '+b,exact:true})).toBeChecked();await expect(diagnoses).toContainText(a);
 await page.getByRole('link',{name:'Diagnosis Master',exact:true}).click();await page.getByLabel('Search catalogue',{exact:true}).fill(b);await page.getByRole('button',{name:'Edit '+b,exact:true}).click();await page.getByLabel('Diagnosis name',{exact:true}).fill(b+' renamed');await page.getByRole('checkbox',{name:'Active for new selections',exact:true}).uncheck();await page.getByLabel('Reason for change',{exact:true}).fill('Fictional catalogue maintenance');await page.getByRole('button',{name:'Save diagnosis',exact:true}).click();await expect(page.getByRole('status')).toContainText('Diagnosis saved successfully');
 await page.getByRole('link',{name:'Doctor Consultations',exact:true}).click();await page.getByRole('button',{name:'Open '+name,exact:true}).click();await expect(diagnoses.getByRole('radio',{name:'Primary diagnosis '+b,exact:true})).toBeChecked();await expect(diagnoses).not.toContainText(b+' renamed');
 page.once('dialog',d=>d.accept());await current.getByRole('button',{name:'Complete Consultation',exact:true}).click();await expect(current).toContainText('COMPLETED');await expect(diagnoses).toContainText(b);await expect(diagnoses.getByRole('button')).toHaveCount(0);
 const doc=await login('doctor','Browser!Doctor2026');const detail=await(await request.get(base+'/doctor-consultations/'+v.visit_id,{headers:doc})).json();expect(detail.diagnoses).toHaveLength(2);expect(detail.diagnoses[0].name).toBe(b);expect(detail.revisions).toHaveLength(3);
 const ordinary=await request.get(base+'/visits/'+v.visit_id,{headers:admin});expect(await ordinary.text()).not.toContain(b);expect(errors).toEqual([]);
});
