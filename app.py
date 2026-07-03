import datetime
import calendar
import re
import pandas as pd
import streamlit as st
from supabase import create_client
from dateutil.relativedelta import relativedelta

# --- CONFIG SUPABASE ---
# ตั้งค่าเชื่อมต่อฐานข้อมูลของคุณ
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 🚀 ระบบป้องกัน Supabase หลับ & Auto-Cleanup (ลบ Waiting List หมดอายุ)
# ==========================================
def initial_system_maintenance():
    try:
        # 1. ยิงคำสั่งไปดึงข้อมูล 1 แถวแบบเบาที่สุด เพื่อกระตุ้นให้ Supabase ทำงาน
        supabase.table("members").select("member_id").limit(1).execute()
        
        # 2. ระบบ Auto-Cleanup: ลบรายชื่อ Waiting List ของวันที่ผ่านไปแล้วโดยไม่ตัดสิทธิ์
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        supabase.table("attendance").delete().eq("booking_status", "Waitlisted").lt("checkin_date", today_str).execute()
    except Exception:
        pass

# สั่งกระตุ้นทันทีที่แอปถูกโหลด
initial_system_maintenance()
# ==========================================

# --- CONFIG หน้าเว็บ ---
st.set_page_config(
    page_title="Fitness Admin System Ultra Pro", page_icon="🏋️‍♂️", layout="wide"
)

# 🔔 แสดงแจ้งเตือนเมื่อมีการเลื่อนคิวอัตโนมัติ (Auto-Promotion) เป็น POP-UP
if "waitlist_promoted_msg" in st.session_state:
    @st.dialog("🔔 เลื่อนคิวสำรองอัตโนมัติสำเร็จ!")
    def waitlist_popup():
        st.success(st.session_state["waitlist_promoted_msg"])
        st.info("💡 แอดมินสามารถโทรแจ้งลูกค้ารายนี้ว่าได้คิวเป็นตัวจริงแล้ว")
        if st.button("รับทราบ", type="primary", use_container_width=True):
            del st.session_state["waitlist_promoted_msg"]
            st.rerun()
    waitlist_popup()

def clean_date_string(raw_val):
    if pd.isna(raw_val) or not raw_val:
        return ""
    val_str = str(raw_val).strip()
    match = re.match(r'^(\d{4}-\d{2}-\d{2})', val_str)
    if match:
        return match.group(1)
    return val_str

# ฟังก์ชันดึงเวลาสำหรับจัดเรียงคลาสในปฏิทิน
def extract_start_time(c_name):
    m = re.search(r'\((\d{2}:\d{2})', str(c_name))
    return m.group(1) if m else "99:99"

# 🚀 โหลดข้อมูลตรงจาก Supabase (ทำงานเร็วมาก)
@st.cache_data(ttl=10)
def load_data_from_supabase(table_name):
    try:
        response = supabase.table(table_name).select("*").execute()
        if response.data:
            return pd.DataFrame(response.data)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการโหลดข้อมูลตาราง {table_name}: {e}")
        return pd.DataFrame()

# ตรรกะระบบแจ้งเตือนผลรวมและเวลาหมดอายุ
def get_advanced_alert_list(df_m, df_c, today):
    if not isinstance(df_m, pd.DataFrame) or df_m.empty: return []
    if not isinstance(df_c, pd.DataFrame) or df_c.empty: return []
        
    alert_data = []
    if "is_deleted" not in df_m.columns: return []
        
    active_m = df_m[df_m["is_deleted"].astype(str).str.strip() == "0"]
    
    # ⚡ SPEED UP: แปลงคอร์สเป็น Dict เพื่อง่ายต่อการดึงข้อมูลกลุ่มรายบุคคล
    df_c_clean = df_c.copy()
    df_c_clean.columns = [c.strip() for c in df_c_clean.columns]
    df_c_clean["member_id_str"] = df_c_clean["member_id"].astype(str).str.strip()
    
    if "is_deleted" in df_c_clean.columns:
        df_c_clean["is_deleted_str"] = df_c_clean["is_deleted"].astype(str).str.strip()
        grouped = df_c_clean[df_c_clean["is_deleted_str"] == "0"].groupby("member_id_str")
    else:
        grouped = df_c_clean.groupby("member_id_str")
        
    courses_by_member = {m_id_str: group for m_id_str, group in grouped}

    for _, m_row in active_m.iterrows():
        try:
            m_id = int(float(str(m_row["member_id"]).strip()))
        except: continue
        
        m_id_str = str(m_id)
        if m_id_str not in courses_by_member: continue
        m_courses = courses_by_member[m_id_str]
        
        total_remaining = 0
        has_expired_but_has_slots = False
        expired_reasons = []
        
        for _, c_row in m_courses.iterrows():
            c_status = str(c_row.get("status", "Inactive")).strip()
            try: rem_p = int(float(str(c_row.get("rem_private", 0)).strip()))
            except: rem_p = 0
            try: rem_d = int(float(str(c_row.get("rem_duo", 0)).strip()))
            except: rem_d = 0
            try: rem_g = int(float(str(c_row.get("rem_group", 0)).strip()))
            except: rem_g = 0
            
            slots = rem_p + rem_d + rem_g
            total_remaining += slots
            
            exp_str = clean_date_string(c_row.get("expiry_date", ""))
            if exp_str:
                try:
                    exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
                    if today > exp_date and slots > 0:
                        has_expired_but_has_slots = True
                        if c_status == "Inactive":
                            expired_reasons.append(f"คอร์ส {c_row.get('course_name','')} หมดเวลาดองสิทธิ์ แต่เหลือรวม {slots} ครั้ง")
                        else:
                            expired_reasons.append(f"คอร์ส {c_row.get('course_name','')} หมดอายุใช้งาน แต่เหลือรวม {slots} ครั้ง")
                except ValueError: continue

        reason = []
        status = "ปกติ"
        
        if total_remaining < 2 and len(m_courses) > 0:
            status = "🚨 สิทธิ์หมด/วิกฤต"
            reason.append(f"🎟️ ยอดรวมทุกสิทธิ์ในทุกคอร์สเหลือ {total_remaining} ครั้ง")
            
        if has_expired_but_has_slots:
            status = "⚠️ คอร์สหมดอายุแต่สิทธิ์เหลือ"
            reason.extend(expired_reasons)

        if status != "ปกติ":
            try: is_f = int(float(str(m_row.get("is_followed", 0)).strip()))
            except: is_f = 0
            alert_data.append({
                "id": m_id, "name": m_row["name"], "phone": m_row["phone"],
                "total_slots": f"{total_remaining} ครั้ง", "status": status,
                "reason": " | ".join(reason), "is_followed": is_f
            })
    return alert_data


# --- เริ่มต้นหน้าหลักแอดมิน ---
st.title("🛡️ Fitness Admin System Ultra Fast (Supabase Hybrid)")
st.markdown("---")

menu = [
    "👥 สมัครสมาชิก & เพิ่มคอร์สใหม่",
    "🛠️ การจัดการคอร์ส",  
    "🏫 จัดการตารางคลาสเรียน",  
    "🎟️ เช็กอินเข้าเรียน (Auto FIFO)",
    "📅 ปฏิทินและประวัติการเข้าคลาส",
    "⚠️ ระบบแจ้งเตือนเงื่อนไขพิเศษ",
    "🧹 ล้างคอร์สที่ไม่ได้ใช้งานเกิน 4 เดือน"
]
choice = st.sidebar.selectbox("เมนูจัดการสตูดิโอ", menu)
today_date = datetime.date.today()

if "cal_shift_manage" not in st.session_state:
    st.session_state["cal_shift_manage"] = 0  
if "cal_shift_checkin" not in st.session_state:
    st.session_state["cal_shift_checkin"] = 0

# 🚀 โหลดข้อมูลลงหน่วยความจำ
df_members = load_data_from_supabase("members")
df_courses = load_data_from_supabase("courses")

# POP-UP ตรวจจับสิทธิ์รวมวิกฤต
if "popup_shown" not in st.session_state:
    st.session_state["popup_shown"] = False

if not df_members.empty and not st.session_state["popup_shown"]:
    all_alerts = get_advanced_alert_list(df_members, df_courses, today_date)
    unfollowed_alerts = [a for a in all_alerts if a["is_followed"] == 0]
    if unfollowed_alerts:
        @st.dialog("🚨 แจ้งเตือนยอดสิทธิ์วิกฤต (< 2 ครั้ง)")
        def show_alert_popup(alerts):
            st.write("พบรายชื่อสมาชิกตรงเงื่อนไขสิทธิ์หมด/วิกฤต:")
            for item in alerts:
                st.markdown(f"- **คุณ {item['name']}** ({item['phone']}) ⮞ `{item['status']}` : {item['reason']}")
            if st.button("รับทราบและปิดหน้าต่าง", type="primary", use_container_width=True):
                st.session_state["popup_shown"] = True ; st.rerun()
        show_alert_popup(unfollowed_alerts)

# ==========================================
# 1. หน้าจัดการและเปิดคอร์สใหม่
# ==========================================
if choice == "👥 สมัครสมาชิก & เพิ่มคอร์สใหม่":
    st.header("👤 ระบบการจัดการ MemberID และ เปิดคอร์สเรียนผสม")
    tab1, tab2 = st.tabs(["➕ สมัคร Member ID ใหม่", "🎟️ ซื้อคอร์สผสม Hybrid ใหม่ให้ ID เดิม"])
    
    with tab1:
        st.subheader("สร้างประวัติสมาชิกใหม่")
        with st.form(key="new_member_form", clear_on_submit=True):
            m_name = st.text_input("ชื่อ-นามสกุลลูกค้า *")
            m_phone = st.text_input("เบอร์โทรศัพท์ *")
            submit_m = st.form_submit_button("บันทึกข้อมูลสมาชิก")
        if submit_m:
            if not m_name.strip() or not m_phone.strip():
                st.error("❌ กรุณากรอกชื่อและเบอร์โทรศัพท์ให้ครบถ้วน")
            else:
                next_m_id = 1 if (df_members.empty or "member_id" not in df_members.columns) else int(pd.to_numeric(df_members["member_id"], errors='coerce').fillna(0).max()) + 1
                try:
                    supabase.table("members").insert({
                        "member_id": next_m_id,
                        "name": m_name.strip(),
                        "phone": m_phone.strip(),
                        "join_date": today_date.strftime('%Y-%m-%d'),
                        "is_deleted": 0
                    }).execute()
                    st.cache_data.clear()
                    st.success(f"🎉 ออกรหัสสำเร็จ! Member ID: {next_m_id}")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ เกิดข้อผิดพลาด: {e}")

    with tab2:
        st.subheader("เปิดคอร์สผสม (กำหนดจำนวนครั้งแยกประเภทคลาสได้ในคอร์สเดียว)")
        if df_members.empty:
            st.info("ยังไม่มีข้อมูลสมาชิกในระบบ")
        else:
            if "is_deleted" in df_members.columns:
                active_m = df_members[df_members["is_deleted"].astype(str).str.strip() == "0"]
            else:
                active_m = df_members
                
            m_options = {f"ID {r['member_id']}: คุณ {r['name']}": r for _, r in active_m.iterrows()}
            selected_m_label = st.selectbox("เลือกสมาชิกที่ต้องการเพิ่มคอร์ส", list(m_options.keys()))
            m_selected = m_options[selected_m_label]
            
            with st.form(key="new_course_form", clear_on_submit=True):
                c_name = st.text_input("ชื่อคอร์สผสม *", placeholder="เช่น คอร์สเหมาใจสปอร์ต มกราคม")
                st.markdown("🎯 **ระบุจำนวนครั้งแยกตามรูปแบบคลาส (หากไม่มีให้กรอก 0)**")
                col_s1, col_s2, col_s3 = st.columns(3)
                with col_s1: slots_private = st.number_input("จำนวนครั้งคลาสเดี่ยว (Private)", min_value=0, value=0)
                with col_s2: slots_duo = st.number_input("จำนวนครั้งคลาสคู่ (Duo)", min_value=0, value=0)
                with col_s3: slots_group = st.number_input("จำนวนครั้งคลาสกลุ่ม (Group)", min_value=0, value=0)
                
                col_dur1, col_dur2 = st.columns(2)
                with col_dur1: inactive_days = st.number_input("⏳ ระยะเวลาดองคอร์ส Inactive Duration (วัน) *", min_value=1, value=90)
                with col_dur2: active_days = st.number_input("🔥 ระยะเวลาใช้งานหลังเปิดคอร์ส Active Duration (วัน) *", min_value=1, value=30)
                
                submit_c = st.form_submit_button("💳 ยืนยันการออกคอร์สผสม")
                
            if submit_c:
                if not c_name.strip():
                    st.error("❌ กรุณาระบุชื่อคอร์ส")
                elif slots_private + slots_duo + slots_group <= 0:
                    st.error("❌ คอร์สต้องมีจำนวนสิทธิ์เรียนอย่างน้อยหนึ่งประเภทคลาส (มากกว่า 0 ครั้ง)")
                else:
                    next_c_id = 1 if (df_courses.empty or "course_id" not in df_courses.columns) else int(pd.to_numeric(df_courses["course_id"], errors='coerce').fillna(0).max()) + 1
                    inactive_expiry = today_date + datetime.timedelta(days=int(inactive_days))
                    
                    try:
                        supabase.table("courses").insert({
                            "course_id": next_c_id,
                            "member_id": int(m_selected["member_id"]),
                            "course_name": c_name.strip(),
                            "total_private": slots_private, "rem_private": slots_private,
                            "total_duo": slots_duo, "rem_duo": slots_duo,
                            "total_group": slots_group, "rem_group": slots_group,
                            "signup_date": today_date.strftime('%Y-%m-%d'),
                            "inactive_duration": int(inactive_days),
                            "active_duration": int(active_days),
                            "expiry_date": inactive_expiry.strftime('%Y-%m-%d'),
                            "status": "Inactive",
                            "is_deleted": 0
                        }).execute()
                        st.cache_data.clear()
                        st.success(f"🎉 บันทึกคอร์สผสมสำเร็จ! สถานะ: Inactive")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ เกิดข้อผิดพลาด: {e}")

    st.markdown("---")
    st.subheader("📋 รายการคอร์สทั้งหมดในระบบ (สิทธิ์คงเหลือแยกประเภทคลาส)")
    
    if not df_courses.empty:
        df_courses.columns = [c.strip() for c in df_courses.columns]
        if "is_deleted" in df_courses.columns:
            df_disp_courses = df_courses[df_courses["is_deleted"].astype(str).str.strip() == "0"].copy()
        else:
            df_disp_courses = df_courses.copy()
            
        if not df_disp_courses.empty and not df_members.empty:
            df_members_clean = df_members[["member_id", "name", "phone"]].copy()
            df_members_clean["member_id"] = df_members_clean["member_id"].astype(str).str.strip()
            df_disp_courses["member_id"] = df_disp_courses["member_id"].astype(str).str.strip()
            
            df_merged = df_disp_courses.merge(df_members_clean, on="member_id", how="left")
            df_merged["member_id_int"] = df_merged["member_id"].astype(int)
            df_merged = df_merged.sort_values(by="member_id_int")

            table_data = []
            for _, r in df_merged.iterrows():
                c_status = str(r.get("status", "Inactive")).strip()
                c_id = int(float(str(r["course_id"])))
                exp_str = clean_date_string(r.get("expiry_date", ""))
                is_expired = False
                if exp_str:
                    try: is_expired = today_date > datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
                    except: pass
                
                status_label = "🟡 Inactive" if c_status == "Inactive" else "🟢 Active"
                if is_expired: status_label += " (หมดอายุ)"

                p_txt = f"P: {r.get('rem_private','0')}/{r.get('total_private','0')}"
                d_txt = f"D: {r.get('rem_duo','0')}/{r.get('total_duo','0')}"
                g_txt = f"G: {r.get('rem_group','0')}/{r.get('total_group','0')}"

                table_data.append({
                    "Member": f"คุณ {r.get('name', '')} (ID: {r.get('member_id', '')})",
                    "Course Info": f"รหัส: {c_id} | {r.get('course_name', '')}",
                    "สิทธิ์คงเหลือ Private": p_txt,
                    "สิทธิ์คงเหลือ Duo": d_txt,
                    "สิทธิ์คงเหลือ Group": g_txt,
                    "วันหมดอายุ": clean_date_string(r.get('expiry_date', '')),
                    "สถานะ": status_label
                })
            st.table(pd.DataFrame(table_data))

# ==========================================
# 2. หน้าจัดการคอร์ส
# ==========================================
elif choice == "🛠️ การจัดการคอร์ส":
    st.header("🛠️ การจัดการคอร์ส แก้ไขข้อมูล และลบรายการ")
    if not df_courses.empty:
        df_courses.columns = [c.strip() for c in df_courses.columns]
        df_members_clean = df_members[["member_id", "name", "phone"]].copy()
        df_members_clean["member_id"] = df_members_clean["member_id"].astype(str).str.strip()
        df_courses["member_id"] = df_courses["member_id"].astype(str).str.strip()
        
        # แสดงเฉพาะคอร์สที่ไม่ได้ถูกลบ
        if "is_deleted" in df_courses.columns:
            df_display_c = df_courses[df_courses["is_deleted"].astype(str).str.strip() == "0"].copy()
        else:
            df_display_c = df_courses.copy()
            
        df_merged = df_display_c.merge(df_members_clean, on="member_id", how="left")
        df_merged["member_id_int"] = df_merged["member_id"].astype(int)
        df_merged = df_merged.sort_values(by="member_id_int")
        
        table_data = []
        for _, r in df_merged.iterrows():
            table_data.append({
                "Member": f"คุณ {r.get('name', '')} (ID: {r.get('member_id', '')})",
                "Course Info": f"รหัส: {int(float(r['course_id']))} | {r.get('course_name', '')}",
                "Private": f"{r.get('rem_private','0')} / {r.get('total_private','0')}",
                "Duo": f"{r.get('rem_duo','0')} / {r.get('total_duo','0')}",
                "Group": f"{r.get('rem_group','0')} / {r.get('total_group','0')}",
                "หมดอายุ": clean_date_string(r.get('expiry_date', '')),
                "สถานะ": r.get('status', 'Inactive')
            })
        st.table(pd.DataFrame(table_data))
        
        st.markdown("---")
        
        # 🌟 แบ่งหน้าแก้ไขเป็น 3 แท็บ เพื่อความสวยงามและเป็นระเบียบ
        tab_course_edit, tab_course_del, tab_member_edit = st.tabs([
            "📝 แก้ไขสิทธิ์คอร์ส", "🗑️ ลบคอร์สเรียน", "👤 แก้ไขข้อมูลสมาชิก"
        ])
        
        # --- TAB 1: แก้ไขคอร์ส ---
        with tab_course_edit:
            st.subheader("📝 แก้ไขสิทธิ์และวันหมดอายุรายคอร์ส")
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                edit_id = st.number_input("ระบุ Course ID ที่ต้องการแก้ไข", min_value=1, step=1, key="edit_c_id")
            
            target = df_courses[df_courses['course_id'].astype(int) == int(edit_id)]
            if not target.empty:
                with col_e2:
                    new_p = st.number_input("แก้สิทธิ์คงเหลือ Private", value=int(float(target['rem_private'].iloc[0])))
                    new_d = st.number_input("แก้สิทธิ์คงเหลือ Duo", value=int(float(target['rem_duo'].iloc[0])))
                    new_g = st.number_input("แก้สิทธิ์คงเหลือ Group", value=int(float(target['rem_group'].iloc[0])))
                    new_expiry = st.date_input("วันหมดอายุใหม่", value=pd.to_datetime(target['expiry_date'].iloc[0]))
                
                if st.button("✅ ยืนยันการแก้ไขข้อมูลคอร์ส"):
                    try:
                        supabase.table("courses").update({
                            "rem_private": new_p,
                            "rem_duo": new_d,
                            "rem_group": new_g,
                            "expiry_date": new_expiry.strftime('%Y-%m-%d')
                        }).eq("course_id", int(edit_id)).execute()
                        st.cache_data.clear()
                        st.success("✅ อัปเดตสิทธิ์ผสมของคอร์สเรียบร้อยแล้ว!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
            else:
                st.info("ระบุ Course ID ด้านบนเพื่อเริ่มการแก้ไข")

        # --- TAB 2: ลบคอร์ส (ใหม่) ---
        with tab_course_del:
            st.subheader("🗑️ ลบคอร์สเรียนออกจากระบบ")
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                del_c_id = st.number_input("ระบุ Course ID ที่ต้องการลบทิ้ง", min_value=1, step=1, key="del_c_id")
            
            target_del = df_courses[df_courses['course_id'].astype(int) == int(del_c_id)]
            if not target_del.empty:
                st.warning(f"⚠️ คุณกำลังจะลบคอร์ส: **{target_del['course_name'].iloc[0]}**")
                if st.button("🚨 ยืนยันการลบคอร์สถาวร", type="primary"):
                    try:
                        supabase.table("courses").delete().eq("course_id", int(del_c_id)).execute()
                        st.cache_data.clear()
                        st.success("🗑️ ลบคอร์สเรียบร้อยแล้ว!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ เกิดข้อผิดพลาดในการลบ: {e}")
            else:
                st.info("ระบุ Course ID เพื่อค้นหาและลบคอร์ส")

        # --- TAB 3: แก้ไขข้อมูลสมาชิก (ใหม่) ---
        with tab_member_edit:
            st.subheader("👤 แก้ไขชื่อและเบอร์โทรศัพท์ของลูกค้า")
            if not df_members.empty:
                if "is_deleted" in df_members.columns:
                    active_m = df_members[df_members["is_deleted"].astype(str).str.strip() == "0"]
                else:
                    active_m = df_members
                    
                m_edit_options = {f"ID {r['member_id']}: คุณ {r['name']}": r for _, r in active_m.iterrows()}
                selected_edit_m = st.selectbox("เลือกสมาชิกที่ต้องการแก้ไขข้อมูล", ["-- กรุณาเลือก --"] + list(m_edit_options.keys()))
                
                if selected_edit_m != "-- กรุณาเลือก --":
                    target_m = m_edit_options[selected_edit_m]
                    with st.form("edit_member_form"):
                        new_name = st.text_input("ชื่อ-นามสกุลใหม่", value=target_m['name'])
                        new_phone = st.text_input("เบอร์โทรศัพท์ใหม่", value=target_m.get('phone', ''))
                        
                        submit_edit_m = st.form_submit_button("💾 บันทึกข้อมูลสมาชิก")
                        
                        if submit_edit_m:
                            try:
                                supabase.table("members").update({
                                    "name": new_name.strip(),
                                    "phone": new_phone.strip()
                                }).eq("member_id", int(target_m['member_id'])).execute()
                                st.cache_data.clear()
                                st.success("✅ อัปเดตข้อมูลสมาชิกเรียบร้อยแล้ว!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# ==========================================
# 3. หน้าจัดการตารางคลาสเรียน
# ==========================================
elif choice == "🏫 จัดการตารางคลาสเรียน":
    st.header("🏫 ระบบบริหารจัดการและวางตารางคลาสเรียน")
    df_classes_check = load_data_from_supabase("classes")
    df_attendance_check = load_data_from_supabase("attendance")
    
    if not df_classes_check.empty:
        df_classes_check.columns = [c.strip() for c in df_classes_check.columns]
    if not df_attendance_check.empty:
        df_attendance_check.columns = [c.strip() for c in df_attendance_check.columns]
    
    with st.expander("➕ เพิ่มตารางคลาสใหม่", expanded=True):
        col_f1, col_f2 = st.columns(2)
        
        # --- 🧠 ระบบความจำ (Memory System) จดจำคลาสและสีที่เลือก ---
        known_classes = []
        class_memory = {}
        known_instructors = []
        
        if not df_classes_check.empty:
            for _, row in df_classes_check.iterrows():
                # ตัดเวลาออกจากชื่อคลาส
                c_full = str(row.get("class_name", ""))
                c_clean = re.sub(r'\s*\(\d{2}:\d{2}\s*-\s*\d{2}:\d{2}\)$', '', c_full).strip()
                
                if c_clean:
                    if c_clean not in known_classes:
                        known_classes.append(c_clean)
                    # 🌟 อัปเดตลง dictionary เสมอเพื่อให้จำค่าใหม่ล่าสุดของคลาสนั้นๆ
                    class_memory[c_clean] = {
                        "instructor": str(row.get("instructor", "")).strip(),
                        "class_type": str(row.get("class_type", "คลาสกลุ่ม (Group)")).strip(),
                        "class_color": str(row.get("class_color", "#E3F2FD")).strip()
                    }
                
                inst = str(row.get("instructor", "")).strip()
                if inst and inst not in known_instructors:
                    known_instructors.append(inst)
                    
        with col_f1:
            insert_mode = st.radio("รูปแบบการลงตาราง", ["เพิ่มวันเดียวแบบปกติ", "ตั้งตารางประจำ (Routine)"])
            
            # 📌 1. เลือกชื่อคลาส (หรือพิมพ์ใหม่)
            class_options = ["📝 พิมพ์ชื่อคลาสใหม่เอง..."] + known_classes
            selected_preset = st.selectbox("📌 เลือกจากคลาสที่เคยสร้างไว้ (หรือพิมพ์ใหม่)", class_options)
            
            if selected_preset == "📝 พิมพ์ชื่อคลาสใหม่เอง...":
                raw_class_name = st.text_input("ชื่อคลาสเรียน *")
                default_type = 2 
                default_color = "#E3F2FD"
                default_inst_idx = 0
            else:
                raw_class_name = selected_preset
                preset = class_memory[selected_preset]
                
                types_list = ["คลาสเดี่ยว (Private)", "คลาสคู่ (Duo)", "คลาสกลุ่ม (Group)"]
                default_type = types_list.index(preset["class_type"]) if preset["class_type"] in types_list else 2
                
                # 🌟 จัดการ Format สีให้ Streamlit ยอมรับ (ต้องเป็น #RRGGBB 7 ตัวอักษร)
                default_color = str(preset.get("class_color", "#E3F2FD")).strip()
                if not re.match(r'^#[0-9a-fA-F]{6}$', default_color): 
                    default_color = "#E3F2FD"
                
                inst_list = ["📝 พิมพ์ชื่อครูใหม่เอง..."] + known_instructors
                default_inst_idx = inst_list.index(preset["instructor"]) if preset["instructor"] in inst_list else 0

            # 📌 2. เลือกครูผู้สอน
            inst_options = ["📝 พิมพ์ชื่อครูใหม่เอง..."] + known_instructors
            sel_inst = st.selectbox("👤 เลือกครูผู้สอน", inst_options, index=default_inst_idx)
            
            if sel_inst == "📝 พิมพ์ชื่อครูใหม่เอง...":
                instructor = st.text_input("ชื่อครูผู้สอน *")
            else:
                instructor = sel_inst

            # 📌 3. ประเภทคลาสและสี (ดึงค่าเริ่มต้นจาก Memory)
            class_type = st.selectbox("ประเภทคลาส *", ["คลาสเดี่ยว (Private)", "คลาสคู่ (Duo)", "คลาสกลุ่ม (Group)"], index=default_type)
            
            # 🌟 อัปเดต: สล็อตเวลา 8:01-9:00, 8:31-9:30, 9:01-10:00 ไปจนถึง 20:31-21:30
            time_slots = []
            for h in range(8, 21):
                time_slots.append(f"{h:02d}:01 - {h+1:02d}:00")
                time_slots.append(f"{h:02d}:31 - {h+1:02d}:30")
                
            selected_time = st.selectbox("⏱️ ระบุเวลาเข้าเรียน *", time_slots, index=4)
            
            chosen_color = st.color_picker("🎨 เลือกสีกล่องปฏิทิน", default_color)
            
        with col_f2:
            if insert_mode == "เพิ่มวันเดียวแบบปกติ":
                single_date = st.date_input("วันที่เปิดสอน", value=today_date)
            else:
                days_of_week = st.multiselect("เลือกวันในสัปดาห์", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
                routine_range = st.selectbox("ระยะเวลาวนลูป", ["1 เดือน", "3 เดือน"])

            if st.button("🚀 บันทึกตารางคลาสเรียน", type="primary"):
                if not raw_class_name.strip():
                    st.error("❌ กรุณากรอกชื่อคลาสเรียน")
                elif not instructor.strip():
                    st.error("❌ กรุณากรอกชื่อครูผู้สอน")
                else:
                    class_name_with_time = f"{raw_class_name.strip()} ({selected_time})"
                    start_id = 1 if (df_classes_check.empty or "class_id" not in df_classes_check.columns) else int(pd.to_numeric(df_classes_check["class_id"], errors='coerce').fillna(0).max()) + 1
                    
                    dates_to_validate = []
                    if insert_mode == "เพิ่มวันเดียวแบบปกติ":
                        dates_to_validate.append(single_date)
                    else:
                        months = 1 if routine_range == "1 เดือน" else 3
                        end_date = today_date + relativedelta(months=months)
                        curr = today_date
                        day_map = {"Monday":0, "Tuesday":1, "Wednesday":2, "Thursday":3, "Friday":4, "Saturday":5, "Sunday":6}
                        target_days = [day_map[d] for d in days_of_week]
                        while curr <= end_date:
                            if curr.weekday() in target_days:
                                dates_to_validate.append(curr)
                            curr += datetime.timedelta(days=1)
                    
                    has_conflict = False
                    conflict_message = ""
                    
                    if not df_classes_check.empty:
                        df_classes_check["clean_db_date"] = df_classes_check["class_date"].apply(clean_date_string)
                        
                        # 🌟 อัปเดต: ระบบป้องกันคลาสทับซ้อนเวลา Overlap (คำนวณจากนาที)
                        sel_s, sel_e = selected_time.split(" - ")
                        sel_start_mins = int(sel_s.split(":")[0]) * 60 + int(sel_s.split(":")[1])
                        sel_end_mins = int(sel_e.split(":")[0]) * 60 + int(sel_e.split(":")[1])
                        
                        for check_date in dates_to_validate:
                            date_str_check = check_date.strftime("%Y-%m-%d")
                            match_date_classes = df_classes_check[df_classes_check["clean_db_date"] == date_str_check]
                            
                            for _, db_row in match_date_classes.iterrows():
                                db_name = str(db_row.get("class_name", ""))
                                db_instructor = str(db_row.get("instructor", "")).strip()
                                db_class_type = str(db_row.get("class_type", "")).strip()
                                
                                m = re.search(r'\((\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})\)', db_name)
                                if m:
                                    db_s_str, db_e_str = m.groups()
                                    db_s = int(db_s_str.split(":")[0]) * 60 + int(db_s_str.split(":")[1])
                                    db_e = int(db_e_str.split(":")[0]) * 60 + int(db_e_str.split(":")[1])
                                    
                                    # เช็กการ Overlap กัน (มีเวลาทับซ้อนกันแม้แต่นาทีเดียว)
                                    if sel_start_mins < db_e and sel_end_mins > db_s:
                                        if db_instructor == instructor.strip():
                                            has_conflict = True
                                            conflict_message = f"❌ ไม่สามารถบันทึกได้: ครู **{instructor.strip()}** มีสอนคลาส '{db_name}' อยู่แล้ว (เวลาทับซ้อน) ในวันที่ {date_str_check}"
                                            break
                                            
                                        if class_type == db_class_type:
                                            has_conflict = True
                                            conflict_message = f"❌ ไม่สามารถบันทึกได้: มีคลาสประเภทเดียวกัน (**{db_class_type}**) เปิดสอนอยู่แล้ว (เวลาทับซ้อน) ในวันที่ {date_str_check}"
                                            break
                                            
                                        if ("Duo" in class_type or "คู่" in class_type) and ("Group" in db_class_type or "กลุ่ม" in db_class_type):
                                            has_conflict = True
                                            conflict_message = f"❌ ไม่สามารถบันทึกได้: มีคลาส **{db_class_type}** เปิดสอนอยู่แล้ว (เวลาทับซ้อน) ในวันที่ {date_str_check}"
                                            break
                                            
                                        if ("Group" in class_type or "กลุ่ม" in class_type) and ("Duo" in db_class_type or "คู่" in db_class_type):
                                            has_conflict = True
                                            conflict_message = f"❌ ไม่สามารถบันทึกได้: มีคลาส **{db_class_type}** เปิดสอนอยู่แล้ว (เวลาทับซ้อน) ในวันที่ {date_str_check}"
                                            break
                            if has_conflict: break
                                
                    if has_conflict:
                        st.error(conflict_message)
                    elif not dates_to_validate:
                        st.error("❌ ไม่พบวันที่เปิดสอนที่ตรงกับเงื่อนไข")
                    else:
                        rows_to_insert = []
                        for final_date in dates_to_validate:
                            rows_to_insert.append({
                                "class_id": start_id,
                                "class_name": class_name_with_time,
                                "instructor": instructor.strip(),
                                "class_date": final_date.strftime('%Y-%m-%d'),
                                "class_type": class_type,
                                "class_color": chosen_color
                            })
                            start_id += 1
                            
                        try:
                            supabase.table("classes").insert(rows_to_insert).execute()
                            st.cache_data.clear()
                            st.success("✨ บันทึกตารางคลาสเรียนสำเร็จและผ่านการตรวจสอบแล้ว!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ เกิดข้อผิดพลาดในการบันทึกตารางสอน: {e}")

    st.markdown("---")
    view_date_manage = today_date + relativedelta(months=st.session_state["cal_shift_manage"])
    
    col_btn1, col_btn2, col_btn3 = st.columns([2, 3, 2])
    with col_btn1:
        if st.session_state["cal_shift_manage"] > -1:
            if st.button("◀️ เดือนก่อนหน้า", use_container_width=True):
                st.session_state["cal_shift_manage"] -= 1; st.rerun()
        else: st.button("◀️ เดือนก่อนหน้า", disabled=True, use_container_width=True)
            
    with col_btn2: st.subheader(f"📅 ตารางภาพรวมคลาสเรียนประจำเดือน ({view_date_manage.strftime('%B %Y')})")
        
    with col_btn3:
        if st.session_state["cal_shift_manage"] < 1:
            if st.button("เดือนถัดไป ▶️", use_container_width=True):
                st.session_state["cal_shift_manage"] += 1; st.rerun()
        else: st.button("เดือนถัดไป ▶️", disabled=True, use_container_width=True)

    if df_classes_check.empty:
        st.info("ยังไม่มีข้อมูลคลาสเรียนในระบบ")
    else:
        df_classes_check["clean_date"] = df_classes_check["class_date"].apply(clean_date_string)
        
        booking_counts = {}
        if not df_attendance_check.empty:
            df_attendance_check["class_id_str"] = df_attendance_check["class_id"].astype(str).str.strip()
            df_attendance_check["booking_status"] = df_attendance_check.get("booking_status", pd.Series(["Confirmed"] * len(df_attendance_check))).fillna("Confirmed")
            booking_counts = df_attendance_check[df_attendance_check["booking_status"] == "Confirmed"]["class_id_str"].value_counts().to_dict()
            
        classes_by_date = {}
        for _, row in df_classes_check.iterrows():
            d_str = row["clean_date"]
            if d_str not in classes_by_date: classes_by_date[d_str] = []
            classes_by_date[d_str].append(row)

        cal = calendar.Calendar(firstweekday=6)
        month_days = cal.monthdatescalendar(view_date_manage.year, view_date_manage.month)
        days_header = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสฯ", "ศุกร์", "เสาร์"]
        
        hc = st.columns(7)
        for idx, d_name in enumerate(days_header):
            hc[idx].markdown(f"<div style='text-align:center; font-weight:bold; background-color:#333333; color:#ffffff; padding:8px; border-radius:4px; border: 1px solid #444444;'>{d_name}</div>", unsafe_allow_html=True)
            
        for week_idx, week in enumerate(month_days):
            cols = st.columns(7)
            for i, day in enumerate(week):
                with cols[i]:
                    if day.month != view_date_manage.month:
                        st.markdown(f"<p style='color:#555555; text-align:center;'>{day.day}</p>", unsafe_allow_html=True)
                    else:
                        is_today_style = "border: 2px solid #FF5722; background-color:#3a2214; color:#ffffff;" if day == today_date else "background-color:#262626; border: 1px solid #444444; color:#ffffff;"
                        st.markdown(f"<div style='{is_today_style} padding:6px; border-radius:4px; font-weight:bold; text-align:center;'>{day.day}</div>", unsafe_allow_html=True)
                        
                        day_str = day.strftime("%Y-%m-%d")
                        match_cls_list = classes_by_date.get(day_str, [])
                        
                        # 🌟 อัปเดต: เรียงคลาสตามช่วงเวลาแทนลำดับการ Register
                        match_cls_list = sorted(match_cls_list, key=extract_start_time)
                        
                        for c_idx, c_row in enumerate(match_cls_list):
                            cls_id = str(int(float(str(c_row["class_id"]))))
                            target_class_type = str(c_row.get("class_type", "Group")).strip()
                            c_bg = c_row.get("class_color", "#E3F2FD")
                            if pd.isna(c_bg) or str(c_bg).strip() == "": c_bg = "#E3F2FD"
                            
                            max_capacity = 10
                            if "Private" in target_class_type or "เดี่ยว" in target_class_type: max_capacity = 1
                            elif "Duo" in target_class_type or "คู่" in target_class_type: max_capacity = 1
                            elif "Group" in target_class_type or "กลุ่ม" in target_class_type: max_capacity = 4
                            
                            current_bookings = booking_counts.get(cls_id, 0)
                            
                            st.markdown(f"""
                            <div style='background-color:{c_bg}; font-size:11px; padding:6px; margin-top:4px; border-radius:4px; border-left:4px solid #1E88E5; color:#000000; font-weight:500; line-height:1.3;'>
                                📌 {c_row.get('class_name','')}<br>
                                👤 ครู: {c_row.get('instructor','')}<br>
                                🎯 หมวด: {target_class_type}<br>
                                <small style='color:#444; font-weight:bold;'>👥 ตัวจริง: {current_bookings}/{max_capacity} คน</small>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            if current_bookings > 0:
                                st.button("🔒 มีคนจองแล้ว", key=f"lock_{cls_id}_{week_idx}_{i}_{c_idx}", disabled=True, use_container_width=True)
                            else:
                                if st.button("❌ ลบคลาส", key=f"del_cls_{cls_id}_{week_idx}_{i}_{c_idx}", type="secondary", use_container_width=True):
                                    try:
                                        supabase.table("classes").delete().eq("class_id", int(cls_id)).execute()
                                        st.cache_data.clear()
                                        st.success("🗑️ ลบคลาสเรียนสำเร็จ!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# ==========================================
# 4. หน้าเช็กอินเข้าเรียน (Auto FIFO)
# ==========================================
elif choice == "🎟️ เช็กอินเข้าเรียน (Auto FIFO)":
    st.header("🎟️ ระบบปฏิทินเช็กอินและคิวสำรอง (Waiting List)")
    if df_members.empty or df_courses.empty:
        st.warning("⚠️ ในระบบต้องมีประวัติสมาชิกและคอร์สเรียนก่อนทำรายการ")
    else:
        st.subheader("👤 1. เลือกรายชื่อสมาชิกที่จะทำรายการ")
        if "is_deleted" in df_members.columns:
            active_m = df_members[df_members["is_deleted"].astype(str).str.strip() == "0"]
        else:
            active_m = df_members
            
        m_options = {f"ID {r['member_id']}: คุณ {r['name']} (📞 {r['phone']})": r for _, r in active_m.iterrows()}
        selected_m_label = st.selectbox("ค้นหาและเลือกรายชื่อลูกค้าเพื่อดูสถานะการเช็กอิน", list(m_options.keys()))
        m_data = m_options[selected_m_label]
        m_id = str(int(float(str(m_data["member_id"]))))
        
        st.markdown("---")
        view_date_checkin = today_date + relativedelta(months=st.session_state["cal_shift_checkin"])
        
        col_cbtn1, col_cbtn2, col_cbtn3 = st.columns([2, 3, 2])
        with col_cbtn1:
            if st.session_state["cal_shift_checkin"] > -1:
                if st.button("◀️ เดือนก่อนหน้า ", use_container_width=True):
                    st.session_state["cal_shift_checkin"] -= 1; st.rerun()
            else: st.button("◀️ เดือนก่อนหน้า ", disabled=True, use_container_width=True)
                
        with col_cbtn2: st.subheader(f"📅 2. ตารางปฏิทินของ คุณ {m_data['name']} ({view_date_checkin.strftime('%B %Y')})")
            
        with col_cbtn3:
            if st.session_state["cal_shift_checkin"] < 1:
                if st.button("เดือนถัดไป ▶️ ", use_container_width=True):
                    st.session_state["cal_shift_checkin"] += 1; st.rerun()
            else: st.button("เดือนถัดไป ▶️ ", disabled=True, use_container_width=True)

        df_classes_all = load_data_from_supabase("classes")
        df_attendance = load_data_from_supabase("attendance")
        
        if df_classes_all.empty:
            st.info("ยังไม่มีข้อมูลตารางสอนคลาสเรียนใดๆ ในระบบ")
        else:
            df_classes_all.columns = [c.strip() for c in df_classes_all.columns]
            df_classes_all["clean_date"] = df_classes_all["class_date"].apply(clean_date_string)
            
            # 🌟 จัดการข้อมูล Attendance (รอรับคอลัมน์ใหม่ booking_status)
            class_stats = {}
            user_bookings_map = {}
            
            if not df_attendance.empty:
                df_attendance.columns = [c.strip() for c in df_attendance.columns]
                df_attendance["booking_status"] = df_attendance.get("booking_status", pd.Series(["Confirmed"] * len(df_attendance))).fillna("Confirmed")
                
                df_attendance["clean_att_date"] = df_attendance["checkin_date"].apply(clean_date_string)
                df_attendance["class_id_str"] = df_attendance["class_id"].astype(str).str.strip()
                df_attendance["member_id_str"] = df_attendance["member_id"].astype(str).str.strip()
                
                # นับสถิติแยกตามคลาส (ตัวจริง vs คิวสำรอง)
                for _, att_row in df_attendance.iterrows():
                    c_id_stat = att_row["class_id_str"]
                    b_status = att_row["booking_status"]
                    
                    if c_id_stat not in class_stats:
                        class_stats[c_id_stat] = {"conf": 0, "wait": 0}
                        
                    if b_status == "Waitlisted": class_stats[c_id_stat]["wait"] += 1
                    else: class_stats[c_id_stat]["conf"] += 1
                    
                    if att_row["member_id_str"] == m_id.strip():
                        user_bookings_map[c_id_stat] = att_row

            classes_by_date_checkin = {}
            for _, row in df_classes_all.iterrows():
                d_str = row["clean_date"]
                if d_str not in classes_by_date_checkin: classes_by_date_checkin[d_str] = []
                classes_by_date_checkin[d_str].append(row)

            cal = calendar.Calendar(firstweekday=6)
            month_days = cal.monthdatescalendar(view_date_checkin.year, view_date_checkin.month)
            days_header = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสฯ", "ศุกร์", "เสาร์"]
            
            hc = st.columns(7)
            for idx, d_name in enumerate(days_header):
                hc[idx].markdown(f"<div style='text-align:center; font-weight:bold; background-color:#333333; color:#ffffff; padding:8px; border-radius:4px; border: 1px solid #444444;'>{d_name}</div>", unsafe_allow_html=True)
                
            for week_idx, week in enumerate(month_days):
                cols = st.columns(7)
                for i, day in enumerate(week):
                    with cols[i]:
                        if day.month != view_date_checkin.month:
                            st.markdown(f"<p style='color:#555555; text-align:center;'>{day.day}</p>", unsafe_allow_html=True)
                        else:
                            is_today_style = "border: 2px solid #FF5722; background-color:#3a2214; color:#ffffff;" if day == today_date else "background-color:#262626; border: 1px solid #444444; color:#ffffff;"
                            st.markdown(f"<div style='{is_today_style} padding:6px; border-radius:4px; font-weight:bold; text-align:center;'>{day.day}</div>", unsafe_allow_html=True)
                            
                            day_str = day.strftime("%Y-%m-%d")
                            match_cls = classes_by_date_checkin.get(day_str, [])
                            
                            # 🌟 อัปเดต: เรียงคลาสตามเวลา
                            match_cls = sorted(match_cls, key=extract_start_time)
                            
                            for c_idx, c_row in enumerate(match_cls):
                                cls_id = str(int(float(str(c_row["class_id"]))))
                                target_class_type = str(c_row["class_type"]).strip()
                                
                                max_capacity = 10
                                max_waitlist = 0
                                if "Private" in target_class_type or "เดี่ยว" in target_class_type: max_capacity = 1
                                elif "Duo" in target_class_type or "คู่" in target_class_type: max_capacity = 1
                                elif "Group" in target_class_type or "กลุ่ม" in target_class_type: 
                                    max_capacity = 4
                                    max_waitlist = 2
                                    
                                current_stats = class_stats.get(cls_id, {"conf": 0, "wait": 0})
                                conf_count = current_stats["conf"]
                                wait_count = current_stats["wait"]
                                
                                is_booked = cls_id in user_bookings_map
                                booked_att_id = None
                                booked_course_id = None
                                user_book_status = None
                                
                                if is_booked:
                                    user_att_row = user_bookings_map[cls_id]
                                    booked_att_id = int(float(str(user_att_row["attendance_id"])))
                                    booked_course_id = int(float(str(user_att_row["course_id"])))
                                    user_book_status = user_att_row.get("booking_status", "Confirmed")

                                # ซ่อนคลาสถ้าเต็มทั้งตัวจริงและสำรอง (และผู้ใช้ไม่ได้จองอยู่)
                                if conf_count >= max_capacity and wait_count >= max_waitlist and not is_booked:
                                    continue  

                                # 🌟 จัดการสีกล่องปฏิทิน
                                box_bg = c_row.get("class_color", "#E3F2FD")
                                border_color = "#1E88E5"
                                
                                if is_booked:
                                    if user_book_status == "Waitlisted":
                                        box_bg = "#FFF9C4" # สีเหลืองสำหรับ Waitlist
                                        border_color = "#FBC02D"
                                    else:
                                        box_bg = "#C8E6C9" # สีเขียวสำหรับตัวจริง
                                        border_color = "#388E3C"
                                elif pd.isna(box_bg) or str(box_bg).strip() == "": 
                                    box_bg = "#E3F2FD"
                                
                                wait_txt = f" | ⏳ สำรอง: {wait_count}/{max_waitlist}" if max_waitlist > 0 else ""
                                capacity_text = f"👥 ตัวจริง: {conf_count}/{max_capacity}{wait_txt}"
                                
                                st.markdown(f"""
                                <div style='background-color:{box_bg}; font-size:11px; padding:6px; margin-top:5px; border-radius:4px; border-left:4px solid {border_color}; color:#000000; font-weight:500; line-height:1.3;'>
                                    <b>📌 {c_row.get('class_name','')}</b><br>
                                    👤 ครู: {c_row.get('instructor','')}<br>
                                    🎯 หมวด: {target_class_type}<br>
                                    <small style='color:#555;'>{capacity_text}</small>
                                </div>
                                """, unsafe_allow_html=True)
                                
                                # =========================
                                # ปุ่มจัดการการจอง
                                # =========================
                                if is_booked:
                                    if user_book_status == "Waitlisted":
                                        if st.button("🗑️ ยกเลิกคิว (Waitlist)", key=f"del_{cls_id}_{week_idx}_{i}_{c_idx}"):
                                            try:
                                                supabase.table("attendance").delete().eq("attendance_id", booked_att_id).execute()
                                                st.cache_data.clear()
                                                st.success("🗑️ ยกเลิกคิวสำรองสำเร็จ (ไม่ได้เสียสิทธิ์)")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"❌ Error: {e}")
                                    
                                    else:
                                        if st.button("🗑️ ยกเลิกคลาส (คืนสิทธิ์)", key=f"del_{cls_id}_{week_idx}_{i}_{c_idx}", type="secondary"):
                                            try:
                                                supabase.table("attendance").delete().eq("attendance_id", booked_att_id).execute()
                                                slot_col = "rem_private"
                                                if "Duo" in target_class_type or "คู่" in target_class_type: slot_col = "rem_duo"
                                                if "Group" in target_class_type or "กลุ่ม" in target_class_type: slot_col = "rem_group"
                                                
                                                res = supabase.table("courses").select(slot_col).eq("course_id", booked_course_id).execute()
                                                if res.data:
                                                    curr_slot = int(res.data[0][slot_col])
                                                    supabase.table("courses").update({slot_col: curr_slot + 1}).eq("course_id", booked_course_id).execute()
                                                
                                                if max_waitlist > 0:
                                                    w_res = supabase.table("attendance").select("*").eq("class_id", int(cls_id)).eq("booking_status", "Waitlisted").order("attendance_id").execute()
                                                    if w_res.data:
                                                        for w_usr in w_res.data:
                                                            w_att_id = w_usr["attendance_id"]
                                                            w_crs_id = w_usr["course_id"]
                                                            w_mem_id = w_usr["member_id"]
                                                            
                                                            c_res = supabase.table("courses").select(f"{slot_col}, status, active_duration").eq("course_id", w_crs_id).execute()
                                                            if c_res.data and int(c_res.data[0][slot_col]) > 0:
                                                                supabase.table("attendance").update({"booking_status": "Confirmed"}).eq("attendance_id", w_att_id).execute()
                                                                
                                                                c_status = str(c_res.data[0].get("status", "Inactive"))
                                                                new_slots_waiter = int(c_res.data[0][slot_col]) - 1
                                                                
                                                                if c_status == "Inactive":
                                                                    active_dur = int(c_res.data[0].get("active_duration", 30))
                                                                    class_date_obj = datetime.datetime.strptime(day_str, "%Y-%m-%d").date()
                                                                    new_exp = (class_date_obj + datetime.timedelta(days=active_dur)).strftime('%Y-%m-%d')
                                                                    supabase.table("courses").update({"status": "Active", "expiry_date": new_exp, slot_col: new_slots_waiter}).eq("course_id", w_crs_id).execute()
                                                                else:
                                                                    supabase.table("courses").update({slot_col: new_slots_waiter}).eq("course_id", w_crs_id).execute()
                                                                
                                                                mem_target = df_members[df_members["member_id"].astype(str).str.strip() == str(w_mem_id)]
                                                                promoted_name = mem_target["name"].iloc[0] if not mem_target.empty else "ไม่ทราบชื่อ"
                                                                promoted_phone = mem_target["phone"].iloc[0] if not mem_target.empty else "ไม่พบเบอร์โทร"
                                                                
                                                                st.session_state["waitlist_promoted_msg"] = f"ระบบได้เลื่อนคิวให้ **คุณ {promoted_name}**\n📞 เบอร์โทร: **{promoted_phone}**\n\nขึ้นเป็นตัวจริงและตัดสิทธิ์คอร์สอัตโนมัติเรียบร้อยแล้ว!"
                                                                break
                                                            else:
                                                                supabase.table("attendance").delete().eq("attendance_id", w_att_id).execute()

                                                st.cache_data.clear()
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"❌ Error: {e}")
                                else:
                                    df_courses.columns = [c.strip() for c in df_courses.columns]
                                    slot_col = "rem_private"
                                    if "Duo" in target_class_type or "คู่" in target_class_type: slot_col = "rem_duo"
                                    if "Group" in target_class_type or "กลุ่ม" in target_class_type: slot_col = "rem_group"
                                    
                                    valid_courses = df_courses[
                                        (df_courses["member_id"].astype(str).str.strip() == m_id) & 
                                        (df_courses[slot_col].astype(float) > 0) & 
                                        (df_courses["status"].astype(str).str.strip().isin(["Active", "Inactive"])) & 
                                        (df_courses["is_deleted"].astype(str).str.strip() == "0")
                                    ].copy()
                                    
                                    if valid_courses.empty:
                                        st.error(f"❌ ไม่มีสิทธิ์คงเหลือสำหรับ {target_class_type}")
                                    else:
                                        valid_courses["clean_signup"] = valid_courses["signup_date"].apply(clean_date_string)
                                        valid_courses = valid_courses.sort_values(by="clean_signup", ascending=True)
                                        
                                        target_course_to_cut = valid_courses.iloc[0]
                                        c_id_to_cut = int(float(str(target_course_to_cut["course_id"])))
                                        c_current_status = str(target_course_to_cut.get("status", "Inactive")).strip()
                                        
                                        try: active_duration_days = int(float(str(target_course_to_cut.get("active_duration", 30))))
                                        except: active_duration_days = 30
                                        
                                        next_att_id = 1 if (df_attendance.empty or "attendance_id" not in df_attendance.columns) else int(pd.to_numeric(df_attendance["attendance_id"], errors='coerce').fillna(0).max()) + 1
                                        new_slots = max(0, int(float(str(target_course_to_cut[slot_col]))) - 1)
                                        
                                        if conf_count < max_capacity:
                                            att_insert_data = {
                                                "attendance_id": next_att_id, "member_id": int(m_id), "class_id": int(cls_id),
                                                "checkin_date": day_str, "course_id": c_id_to_cut, "booking_status": "Confirmed"
                                            }
                                            if st.button("🎟️ จองคลาส (ตัวจริง)", key=f"cut_{cls_id}_{week_idx}_{i}_{c_idx}", type="primary"):
                                                if c_current_status == "Inactive":
                                                    @st.dialog("⚠️ ยืนยันการเปิดใช้งานคอร์สเรียนผสม")
                                                    def confirm_and_activate(att_data, c_id, s_col, n_slots, class_dt_str, days_limit):
                                                        st.warning("💡 คอร์สผสมนี้ปัจจุบันมีสถานะเป็น Inactive")
                                                        st.write(f"การเช็กอินเรียนคลาสนี้ในวันที่ **{class_dt_str}** จะเปิดการทำงานคอร์ส (Active) ทันที")
                                                        class_date_obj = datetime.datetime.strptime(class_dt_str, "%Y-%m-%d").date()
                                                        calculated_expiry = class_date_obj + datetime.timedelta(days=days_limit)
                                                        st.info(f"📅 เริ่มนับเวลา **{days_limit} วัน** วันหมดอายุใหม่คือ: **{calculated_expiry.strftime('%Y-%m-%d')}**")
                                                        
                                                        if st.button("✅ ยืนยันเปิด Active และหักแต้ม", type="primary", use_container_width=True):
                                                            try:
                                                                supabase.table("attendance").insert(att_data).execute()
                                                                supabase.table("courses").update({s_col: n_slots, "status": "Active", "expiry_date": calculated_expiry.strftime('%Y-%m-%d')}).eq("course_id", c_id).execute()
                                                                st.cache_data.clear()
                                                                st.balloons()
                                                                st.rerun()
                                                            except Exception as e: st.error(f"❌ Error: {e}")
                                                    confirm_and_activate(att_insert_data, c_id_to_cut, slot_col, new_slots, day_str, active_duration_days)
                                                else:
                                                    try:
                                                        supabase.table("attendance").insert(att_insert_data).execute()
                                                        supabase.table("courses").update({slot_col: new_slots}).eq("course_id", c_id_to_cut).execute()
                                                        st.cache_data.clear()
                                                        st.balloons()
                                                        st.rerun()
                                                    except Exception as e: st.error(f"❌ Error: {e}")
                                        
                                        elif wait_count < max_waitlist:
                                            att_insert_waitlist = {
                                                "attendance_id": next_att_id, "member_id": int(m_id), "class_id": int(cls_id),
                                                "checkin_date": day_str, "course_id": c_id_to_cut, "booking_status": "Waitlisted"
                                            }
                                            if st.button("📝 ลงคิวสำรอง (Waitlist)", key=f"wait_{cls_id}_{week_idx}_{i}_{c_idx}"):
                                                try:
                                                    supabase.table("attendance").insert(att_insert_waitlist).execute()
                                                    st.cache_data.clear()
                                                    st.success("📝 ลงชื่อสำรองสำเร็จ! จะไม่ถูกหักสิทธิ์จนกว่าจะได้รับการเลื่อนคิว")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"❌ Error: {e}")

# ==========================================
# 5. หน้าประวัติการเข้าคลาส
# ==========================================
elif choice == "📅 ปฏิทินและประวัติการเข้าคลาส":
    st.header("📅 บันทึกการเข้าคลาสและประวัติภาพรวมหลังบ้าน")
    df_attendance = load_data_from_supabase("attendance")
    df_classes = load_data_from_supabase("classes")
    
    if df_attendance.empty or df_members.empty or df_classes.empty: 
        st.info("ยังไม่มีข้อมูลประวัติการเข้าคลาสเรียน")
    else:
        df_attendance.columns = [c.strip() for c in df_attendance.columns]
        df_classes.columns = [c.strip() for c in df_classes.columns]
        df_members_clean = df_members[["member_id", "name", "phone"]].copy()
        df_members_clean.columns = [c.strip() for c in df_members_clean.columns]
        
        df_attendance["booking_status"] = df_attendance.get("booking_status", pd.Series(["Confirmed"] * len(df_attendance))).fillna("Confirmed")
        df_attendance["class_id"] = df_attendance["class_id"].astype(str).str.strip()
        df_classes["class_id"] = df_classes["class_id"].astype(str).str.strip()
        df_attendance["member_id"] = df_attendance["member_id"].astype(str).str.strip()
        df_members_clean["member_id"] = df_members_clean["member_id"].astype(str).str.strip()
        
        df_merged = df_attendance.merge(df_members_clean, on="member_id", how="left")
        df_final = df_merged.merge(df_classes[["class_id", "class_name", "class_type", "instructor"]], on="class_id", how="left")
        
        def extract_time(c_name):
            if pd.isna(c_name): return "-"
            m = re.search(r'\(([\d]{2}:[\d]{2}\s*-\s*[\d]{2}:[\d]{2})\)', str(c_name))
            return m.group(1) if m else "-"
            
        df_final["class_time"] = df_final["class_name"].apply(extract_time)
        df_final["class_name"] = df_final["class_name"].apply(lambda x: re.sub(r'\s*\([\d]{2}:[\d]{2}\s*-\s*[\d]{2}:[\d]{2}\)$', '', str(x)).strip() if pd.notna(x) else str(x))
        
        display_cols = []
        col_map = {
            "attendance_id": "รหัสเช็กอิน",
            "checkin_date": "วันที่เข้าเรียน",
            "member_id": "Member ID",
            "name": "ชื่อลูกค้า",
            "class_name": "ชื่อคลาสเรียน",
            "booking_status": "สถานะคิว (จอง/สำรอง)",
            "class_type": "ประเภทคลาส (Private/Duo/Group)",
            "class_time": "เวลาเรียน",
            "instructor": "ครูผู้สอน (Instructor)",
            "course_id": "รหัสคอร์สที่ตัดสิทธิ์"
        }
        
        rename_dict = {}
        for eng_col, thai_col in col_map.items():
            if eng_col in df_final.columns:
                display_cols.append(eng_col)
                rename_dict[eng_col] = thai_col
                
        df_display = df_final[display_cols].copy()
        df_display.rename(columns=rename_dict, inplace=True)
        
        if "วันที่เข้าเรียน" in df_display.columns:
            df_display["วันที่เข้าเรียน"] = df_display["วันที่เข้าเรียน"].apply(clean_date_string)
            df_display = df_display.sort_values(by="วันที่เข้าเรียน", ascending=False)
            
        st.dataframe(df_display, use_container_width=True, hide_index=True)

elif choice == "⚠️ ระบบแจ้งเตือนเงื่อนไขพิเศษ":
    st.header("🚨 หน้ารวมรายชื่อวิกฤต (สิทธิ์รวม < 2 หรือ เวลาหมดแต่สิทธิ์เหลือ)")
    alert_list = get_advanced_alert_list(df_members, df_courses, today_date)
    if not alert_list: st.success("🟢 ทุกคนปกติสุขดีครับ")
    else:
        for item in alert_list:
            st.write(f"👤 คุณ {item['name']} - {item['status']} : {item['reason']}")

elif choice == "🧹 ล้างคอร์สที่ไม่ได้ใช้งานเกิน 4 เดือน":
    st.header("🧹 ระบบคัดกรองล้างฐานข้อมูลคอร์สที่ไม่มีความเคลื่อนไหวเกิน 4 เดือน")
    st.info("คอร์สย่อยเก่าๆ ที่ไม่มีการมาลงชื่อเรียนเกิน 4 เดือนจะแสดงที่นี่เพื่อให้แอดมินกดลบทำความสะอาดโดยไม่กระทบกับข้อมูล Member ID หลัก")
