/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/**
 * @typedef {Object} ScheduleVersion
 * @property {number} id
 * @property {number} version_no
 * @property {string} timezone
 * @property {string[]} workdays
 * @property {string} handover_time
 * @property {string[]} paused_dates
 * @property {number} effective_from
 * @property {string} note
 */
/**
 * @typedef {Object} ReportSchedule
 * @property {number} id
 * @property {string} name
 * @property {number} job_id
 * @property {string} destination
 * @property {number|null} next_run
 * @property {boolean} enabled
 * @property {'interval'|'calendar'} schedule_mode
 * @property {string|null} start_date
 * @property {ScheduleVersion[]} [versions]
 */
/**
 * @typedef {Object} ShiftSlot
 * @property {number} id
 * @property {number} version_id
 * @property {string} slot_key
 * @property {string} slot_date
 * @property {string} local_time
 * @property {number|null} scheduled_at
 * @property {'pending'|'delivered'|'skipped'} status
 * @property {string} dst_note
 * @property {string} last_error
 * @property {number|null} delivered_at
 */
export {};
