export type Lookup={id:string;code:string;name:string};
export type Named={id:string;name:string};
export type District=Named&{region_id:string};
export type Locality=Named&{district_id:string;approval_status:string};
export type Branch={id:string;code:string;name:string};
export type Doctor={id:string;code:string;name:string};
export type Bootstrap={
  organization_id:string;
  branches:Branch[];
  doctors:Doctor[];
  lead_sources:Lookup[];
  lead_statuses:Lookup[];
  lost_reasons:Lookup[];
  appointment_statuses:Lookup[];
  services:Lookup[];
  visit_types:Lookup[];
  visit_statuses:Lookup[];
  chief_complaints:Named[];
  regions:Named[];
  districts:District[];
  localities:Locality[];
};
export type Lead={lead_source_id:string;lead_status_id:string;preferred_branch_id?:string|null;lead_owner_user_id?:string|null;owner_name?:string|null;lost_reason_id?:string|null;interactions?:{interaction_id:string;type:string;summary?:string|null;outcome?:string|null;interaction_at:string}[];status_history?:{code:string;status:string;changed_at:string;reason?:string|null}[];dnc_history?:{old_dnc:boolean;new_dnc:boolean;reason?:string|null;changed_at:string}[];lead_id:string;lead_name:string;mobile?:string|null;age?:number|null;gender?:string|null;concern_text?:string|null;source?:string|null;source_code?:string|null;status?:string|null;status_code?:string|null;preferred_branch?:string|null;dnc:boolean;next_followup_at?:string|null;last_interaction_at?:string|null;created_at?:string;updated_at?:string;row_version:number};
export type Appointment={appointment_id:string;branch_id:string;branch?:string|null;doctor_id?:string|null;doctor?:string|null;lead_id?:string|null;lead_name?:string|null;patient_id?:string|null;scheduled_start:string;scheduled_end:string;status?:string|null;status_code?:string|null;booked_via:string;row_version:number};
export type Patient={patient_id:string;uhid:string;full_name:string;gender?:string|null;dob?:string|null;age?:number|null;primary_mobile?:string|null;alternate_mobile?:string|null;area?:string|null;last_visit_at?:string|null;registration_branch_id:string;profile_status:string;row_version:number;match_reasons?:string[];address?:{region_id?:string|null;region?:string|null;district_id?:string|null;district?:string|null;locality_id?:string|null;locality?:string|null;address_line?:string|null}|null;lead_ids?:string[]};
export type ConversionPreview={lead_id:string;lead_name:string;mobile?:string|null;age?:number|null;gender?:string|null;concern_text?:string|null;preferred_branch_id?:string|null;already_converted_patient_id?:string|null;candidates:Patient[]};
export type Visit={visit_id:string;patient_id:string;patient_name?:string|null;uhid?:string|null;appointment_id?:string|null;branch_id:string;branch?:string|null;doctor_id?:string|null;doctor?:string|null;visit_type_id?:string;visit_type?:string|null;visit_type_code?:string|null;visit_status_id?:string;status?:string|null;status_code?:string|null;checkin_at:string;started_at?:string|null;completed_at?:string|null;followup_at?:string|null;complaints?:Named[];row_version:number};
export type FinanceSetup={
  payment_modes:{id:string;code:string;name:string}[];
  active_policy:{id:string;name:string;free_followup_window_days:number;max_free_followups:number;effective_from:string}|null;
  fee_versions:{id:string;service_id:string;doctor_id?:string|null;branch_id?:string|null;amount:string;effective_from:string;effective_until?:string|null;active:boolean}[];
};
export type FinanceDecision={
  visit_id:string;patient_id:string;patient_name:string;uhid:string;status:string;
  entitlement_id?:string|null;valid_until?:string|null;bill_id?:string|null;bill_number?:string|null;
  bill_status?:string|null;clearance_type?:string|null;clearance_status?:string|null;
  fee_version_id?:string|null;amount?:string|null;paid_amount:string;balance?:string|null;
};
export type ConsultationBill={
  consultation_bill_id:string;bill_number?:string|null;patient_id:string;visit_id:string;doctor_id:string;branch_id:string;
  fee_version_id:string;gross_amount:string;discount_amount:string;net_amount:string;bill_status:string;finalized_at?:string|null;row_version:number;
};
export type ConsultationPayment={payment_id:string;consultation_bill_id:string;amount:string;payment_mode_id:string;received_by:string;received_at:string;branch_id:string;payment_status:string;row_version:number};
export type DailyFinance={report_date:string;branch_id?:string|null;doctor_id?:string|null;total_consultation_visits:number;paid_consultations:number;free_followups:number;complimentary_consultations:number;total_collection:string;cash:string;upi:string;card:string;other:string};
export type PendingMaster={master_type:"LOCALITY"|"CHIEF_COMPLAINT";id:string;name:string;parent_id?:string|null;created_by?:string|null;created_by_name?:string|null;created_at?:string|null;usage_count:number};
export type ImportBatch={import_batch_id:string;file_name:string;status:string;total_rows:number;imported_rows:number;error_rows:number;duplicate_rows:number;created_at?:string};
export type ImportPreviewRow={staging_id:string;row:number;data:Record<string,unknown>;candidates?:{patient_id:string;uhid:string;full_name:string;age?:number|null;gender?:string|null;primary_mobile?:string|null;match_reasons?:string[]}[];validation_status:string;matched_patient_id?:string|null;import_action:string;error_message?:string|null};
export type ImportPreview={batch:{id:string;file_name:string;status:string;total_rows:number;duplicate_rows:number;error_rows:number};rows:ImportPreviewRow[]};
export type AuditEvent={audit_event_id:string;entity_type:string;entity_id:string;action:string;actor_user_id?:string|null;actor_name?:string|null;before_data?:Record<string,unknown>|null;after_data?:Record<string,unknown>|null;reason?:string|null;occurred_at:string};
export type BillDocument={document_type:string;organization:string;bill_id:string;bill_number?:string|null;bill_status:string;bill_date:string;patient:{patient_id:string;uhid:string;name:string;gender?:string|null;mobile?:string|null};branch:{id:string;name?:string|null;address?:string|null;phone?:string|null};doctor:{id:string;name?:string|null};amounts:{gross:string;discount:string;net:string;paid:string;balance:string};payments:{payment_id:string;amount:string;mode?:string|null;received_at:string}[]};
export type ReceiptDocument={document_type:string;organization:string;receipt_id:string;payment_date:string;bill_number?:string|null;patient:{patient_id:string;uhid:string;name:string;mobile?:string|null};branch:{id:string;name?:string|null;address?:string|null;phone?:string|null};doctor:{id:string;name?:string|null};payment:{amount:string;mode?:string|null;status:string};bill:{net:string;total_paid:string;balance:string}};

export type ProcedureExecution={procedure_execution_id:string;procedure_order_id:string;performed_visit_id?:string|null;rendering_branch_id:string;rendering_branch?:string|null;performed_by_doctor_id:string;doctor?:string|null;status?:string|null;started_at?:string|null;completed_at?:string|null;clinical_notes?:string|null;row_version:number};
export type ProcedureOrder={procedure_order_id:string;patient_id:string;patient_name?:string|null;uhid?:string|null;ordered_from_visit_id:string;service_id:string;service_code?:string|null;service_name?:string|null;doctor_id:string;doctor?:string|null;ordering_branch_id:string;ordering_branch?:string|null;order_status?:string|null;financial_status:string;external_reference?:string|null;ordered_at:string;notes?:string|null;row_version:number;executions:ProcedureExecution[]};
export type ProcedureSetup={services:Lookup[];financial_statuses:string[];ready_financial_statuses:string[]};
