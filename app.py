import streamlit as st
import dataset
import calculation as calc
import pandas as pd
import random
import copy
import plotly.graph_objects as go
import optimizer  # <--- IMPORT THE NEW BRAIN

# ==============================================================================
# UI CONFIGURATION & CSS
# ==============================================================================

# 1. Page Config
st.set_page_config(page_title="koi", layout="wide")

def local_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except FileNotFoundError:
        st.markdown("""
        <style>
            .main-title { font-size: 2.5rem; font-weight: 800; margin-bottom: 0; text-align: center; }
            .sub-title { font-size: 1rem; margin-bottom: 1rem; text-align: center; opacity: 0.7; }
        </style>
        """, unsafe_allow_html=True)

local_css("style.css")

# --- FLOATING HUD CSS & JS ---
st.markdown("""
<style>
    .floating-hud {
        position: fixed !important; bottom: 20px !important; right: 20px !important;
        background: rgba(15, 23, 42, 0.95); padding: 20px; border-radius: 12px;
        z-index: 999999; backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.15); box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
        width: 340px; transition: all 0.3s ease; display: flex; flex-direction: column; gap: 10px;
    }
    .hud-title { color: #e2e8f0; font-size: 1.1rem; font-weight: 700; margin-bottom: 5px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; letter-spacing: 0.5px; }
    .hud-label { font-size: 0.8rem; color: #38bdf8; font-weight: 600; text-transform: uppercase; margin-top: 5px; margin-bottom: 2px; }
    .floating-hud button { font-weight: bold !important; border-radius: 6px !important; height: 35px !important; font-size: 0.8rem !important; }
    .floating-hud div[data-testid="stSlider"] { padding-top: 0px; padding-bottom: 15px; }
    .floating-hud div[data-testid="stSlider"] label { color: #94a3b8 !important; font-size: 0.8rem !important; }
</style>
<script>
    function setupHud() {
        const marker = window.parent.document.getElementById('hud-marker');
        if (marker) {
            const container = marker.closest('[data-testid="stVerticalBlock"]');
            if (container) { container.classList.add('floating-hud'); }
        }
    }
    setInterval(setupHud, 500);
</script>
""", unsafe_allow_html=True)

# 2. Session State Initialization
if 'database' not in st.session_state:
    if hasattr(dataset, 'get_data'): st.session_state['database'] = dataset.get_data()
    elif hasattr(dataset, 'STATIC_DATABASE'): st.session_state['database'] = dataset.STATIC_DATABASE
    else: st.session_state['database'] = []

if 'saved_items' not in st.session_state: st.session_state['saved_items'] = []
if 'container_items' not in st.session_state: st.session_state['container_items'] = []
if 'container_plan' not in st.session_state: st.session_state['container_plan'] = None
if 'should_focus_desc' not in st.session_state: st.session_state['should_focus_desc'] = False
if 'last_chart_sel' not in st.session_state: st.session_state['last_chart_sel'] = []
if 'last_table_sel' not in st.session_state: st.session_state['last_table_sel'] = []

for item in st.session_state['saved_items']:
    if "Delete" not in item: item["Delete"] = False

defaults = {'calc_w': "", 'calc_l': "", 'calc_h': "", 'calc_code': "", 'calc_plates': 3}
for key, default in defaults.items():
    if key not in st.session_state: st.session_state[key] = default

# 3. Custom CSS
st.markdown("""
<style>
    .main-title { font-size: 2.5rem; font-weight: 800; margin-bottom: 0; text-align: center; }
    .sub-title { font-size: 1rem; margin-bottom: 1rem; text-align: center; opacity: 0.7; }
    .stTextInput > label, .stNumberInput > label { font-size: 0.85rem; font-weight: 600; margin-bottom: 0.2rem; }
    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem; opacity: 0.7; }
    div[data-testid="stVerticalBlock"] { gap: 0.5rem !important; }
    hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
    .stDataFrame { font-size: 0.8rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    div[data-testid="column"] { text-align: center; }
</style>
""", unsafe_allow_html=True)

# 4. Header
st.markdown('<div class="main-title">Koi<span style="color:#3b82f6">Koi</span> PRO</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">404</div>', unsafe_allow_html=True)

# ==============================================================================
# LOGIC & CALLBACKS
# ==============================================================================
def update_inputs_from_search():
    query = st.session_state.calc_search_query.strip().upper()
    found = next((item for item in st.session_state['database'] if item["code"] == query), None)
    if found:
        st.session_state.calc_w = str(found['width'])
        st.session_state.calc_l = str(found['length'])
        st.session_state.calc_h = str(found['height'])
        st.session_state.calc_code = found['code']
        st.session_state.calc_plates = calc.auto_detect_plates(found['code'])
        st.session_state.calc_sc = 5.0
        st.session_state.calc_mt = 5.0
        st.toast(f"Data loaded for {query}", icon="✅")
    elif query:
        st.toast("Code not found. Please enter dimensions manually.", icon="ℹ️")

def clear_search():
    if st.session_state.calc_search_query: st.session_state.calc_search_query = ""

def on_code_change():
    clear_search()
    st.session_state.calc_sc = 1.0
    st.session_state.calc_mt = 1.0

def add_to_list(data, code, w, l, h, qty):
    new_item = {
        "Delete": False, "Description": f"{w}x{l}x{h} ({code})", "Qty": int(qty),
        "Unit Wt": float(round(data['unit_wt'], 3)), "Total Wt": float(round(data['grand_total'], 2)),
        "_dim_w": float(w), "_dim_l": float(l), "_dim_h": float(h)
    }
    st.session_state['saved_items'].append(new_item)
    st.toast("Item added to list!", icon="📋")

def clear_list(): st.session_state['saved_items'] = []

def display_results(width, length, height, code, quantity, side_cover, metal_thk, plate_count):
    if not (width and length and height and code):
        st.info("👋 Enter dimensions or search code.")
        return
    try:
        data = calc.calculate_specs(width, length, height, code, quantity, side_cover, metal_thk, plate_count)
    except Exception as e:
        st.warning(f"Waiting for valid inputs... ({e})")
        return

    is_solid = data.get('is_solid', False)
    shape = "ROUND" if data.get('is_round') else "RECTANGULAR"
    
    with st.container(border=True):
        r1_col1, r1_col2 = st.columns([3, 1])
        r1_col1.caption(f"RESULTS: {shape} {'(SOLID)' if is_solid else ''}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Unit Weight", f"{data['unit_wt']:.3f} kg")
        c2.metric("Total Vol", f"{data['total_vol']:,.0f} cc")
        c3.metric("Rubber Vol", f"{data['rubber_vol']:,.0f} cc")
        st.divider()
        st.markdown("**Configuration**")
        d1, d2 = st.columns(2)
        if is_solid:
            d1.info("Solid Rubber (N)")
            d2.caption(f"SG: 1.4")
        else:
            d1.caption(f"Metals: {data['metal_w']:.0f}x{data['metal_l']:.0f}mm")
            d1.caption(f"Plates: {plate_count} pcs ({metal_thk}mm)")
            d2.caption(f"Metal Wt: {data['metal_wt']:.3f} kg")
            d2.caption(f"Comp Wt: {data['compound_wt']:.3f} kg")
        st.divider()
        t1, t2 = st.columns([1.5, 1])
        t1.subheader(f"Total: {data['grand_total']:,.2f} kg")
        if t2.button("Add to List ➕", use_container_width=True, type="primary"):
            add_to_list(data, code, width, length, height, quantity)

# ==============================================================================
# MAIN LAYOUT (TABS)
# ==============================================================================
tab1, tab2 = st.tabs(["Calculator", "3d cont"])

# --- TAB 1: CALCULATOR ---
with tab1:
    calc_col, list_col = st.columns([1.5, 1], gap="medium")
    with calc_col:
        with st.container(border=True):
            st.markdown("**Calculator**")
            col_search, col_qty = st.columns([2.5, 1])
            with col_search: st.text_input("Search", placeholder="Code...", key="calc_search_query", on_change=update_inputs_from_search, label_visibility="collapsed")
            with col_qty: calc_qty = st.number_input("Qty", value=1, min_value=1, key='calc_qty', label_visibility="collapsed")
            st.divider()
            c1, c2, c3, c4 = st.columns(4)
            c1.text_input("W", key="calc_w", on_change=clear_search)
            c2.text_input("L", key="calc_l", on_change=clear_search)
            c3.text_input("H", key="calc_h", on_change=clear_search)
            c4.text_input("Code", key="calc_code", on_change=on_code_change)
            
            current_code = st.session_state.calc_code.upper() if st.session_state.calc_code else ""
            is_solid_calc = 'N' in current_code
            if is_solid_calc:
                st.caption("Solid (N) - No internal settings.")
                calc_side_cover, calc_metal_thk, calc_plates = 0.0, 0.0, 0
            else:
                s1, s2, s3 = st.columns(3)
                calc_side_cover = s1.number_input("S.Cover", value=5.0, step=0.5, key='calc_sc')
                calc_metal_thk = s2.number_input("M.Thk", value=5.0, step=0.5, key='calc_mt')
                calc_plates = s3.number_input("Plates", 0, key='calc_plates')
        st.write("") 
        display_results(st.session_state.calc_w, st.session_state.calc_l, st.session_state.calc_h, st.session_state.calc_code, calc_qty, calc_side_cover, calc_metal_thk, calc_plates)

    with list_col:
        st.markdown("**Project List**")
        st.caption("Edit 'Qty' to update. Select '❌' to remove.")
        if len(st.session_state['saved_items']) > 0:
            df = pd.DataFrame(st.session_state['saved_items'])
            edited_df = st.data_editor(
                df,
                column_config={
                    "Delete": st.column_config.CheckboxColumn("❌", width="small"),
                    "Description": st.column_config.TextColumn("Item", width="medium", disabled=True),
                    "Qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, width="small"),
                    "Unit Wt": st.column_config.NumberColumn("Unit (kg)", format="%.3f", disabled=True),
                    "Total Wt": st.column_config.NumberColumn("Total (kg)", format="%.2f", disabled=True),
                    "_dim_w": None, "_dim_l": None, "_dim_h": None
                },
                hide_index=True, use_container_width=True, key="list_editor",
                column_order=("Delete", "Description", "Qty", "Total Wt") 
            )
            changes_detected = False
            if edited_df['Delete'].any():
                edited_df = edited_df[~edited_df['Delete']]
                edited_df['Delete'] = False
                changes_detected = True
            new_totals = edited_df['Qty'] * edited_df['Unit Wt']
            if not edited_df['Total Wt'].equals(new_totals):
                edited_df['Total Wt'] = new_totals
                changes_detected = True
            if changes_detected:
                st.session_state['saved_items'] = edited_df.to_dict('records')
                st.rerun()
            total_project_weight = edited_df['Total Wt'].sum()
            st.divider()
            st.metric("Project Total Weight", f"{total_project_weight:,.2f} kg")
            if st.button("Clear All Items", type="secondary", use_container_width=True):
                clear_list()
                st.rerun()
        else:
            st.info("List is empty.")

# --- TAB 2: CONTAINER LOADING ---
with tab2:
    st.markdown("### 3d  Cont")
    row1_col1, row1_col2 = st.columns([1, 2], gap="large")

    # --- LEFT: INPUTS ---
    with row1_col1:
        with st.container(border=True):
            st.subheader("1. Container Settings")
            cont_type = st.radio("Type", ["40ft High Cube", "20ft Standard"], horizontal=True, key="cont_type_select")
            c_dim1, c_dim2, c_dim3 = st.columns(3)
            if cont_type == "40ft High Cube":
                cont_l = c_dim1.number_input("L (mm)", value=12000, key="dim_l")
                cont_w = c_dim2.number_input("W (mm)", value=2400, key="dim_w")
                cont_h = c_dim3.number_input("H (mm)", value=2400, key="dim_h")
            else:
                cont_l = c_dim1.number_input("L (mm)", value=5800, key="dim_l_20")
                cont_w = c_dim2.number_input("W (mm)", value=2300, key="dim_w_20")
                cont_h = c_dim3.number_input("H (mm)", value=2400, key="dim_h_20")
            
            st.divider()
            st.markdown("### 📦 Stacking")
            stack_mode = st.radio("Stacking Policy", ["Enable Stacking", "Disable Stacking"], index=0, horizontal=True)
            enable_stacking_flag = (stack_mode == "Enable Stacking")
            min_gap_val = st.number_input("Gap (mm)", value=0.0, step=10.0, help="Minimum space between items.")
        
        st.subheader("2. Packing List")
        if st.button("🗑️ Clear List", type="secondary", use_container_width=True):
            st.session_state['container_items'] = []
            st.rerun()

        # Initialize manual inputs
        if 'input_desc' not in st.session_state: st.session_state['input_desc'] = ""
        if 'input_l' not in st.session_state: st.session_state['input_l'] = 0
        if 'input_w' not in st.session_state: st.session_state['input_w'] = 0
        if 'input_h' not in st.session_state: st.session_state['input_h'] = 0
        if 'input_wt' not in st.session_state: st.session_state['input_wt'] = 0.0
        if 'input_qty' not in st.session_state: st.session_state['input_qty'] = 1
        if 'input_pack_type' not in st.session_state: st.session_state['input_pack_type'] = 1
        
        def add_item_callback():
            if (st.session_state.input_l > 0 and st.session_state.input_w > 0 and st.session_state.input_h > 0 and st.session_state.input_wt > 0):
                new_item = {
                    "Delete": False,
                    "Description": st.session_state.input_desc if st.session_state.input_desc else "Item",
                    "Length (mm)": int(st.session_state.input_l),
                    "Width (mm)": int(st.session_state.input_w),
                    "Height (mm)": int(st.session_state.input_h),
                    "Weight (kg)": float(st.session_state.input_wt),
                    "Qty": int(st.session_state.input_qty),
                    "Type": st.session_state.input_pack_type
                }
                st.session_state['container_items'].append(new_item)
                st.toast("Item added!", icon="✅")
                st.session_state.input_desc = ""
                st.session_state.input_l = 0
                st.session_state.input_w = 0
                st.session_state.input_h = 0
                st.session_state.input_wt = 0.0
                st.session_state.input_qty = 1
                st.session_state['should_focus_desc'] = True
            else:
                st.error("Please enter valid dimensions and weight.")

        with st.container(border=True):
            st.markdown("**:heavy_plus_sign: Add Item**")
            st.text_input("Description", placeholder="Item Name...", key="input_desc")
            st.number_input("Length (mm)", min_value=0, step=10, key="input_l")
            st.number_input("Width (mm)", min_value=0, step=10, key="input_w")
            st.number_input("Height (mm)", min_value=0, step=10, key="input_h")
            c_wt, c_qty, c_type = st.columns(3)
            with c_wt: st.number_input("Weight (kg)", min_value=0.0, step=0.1, key="input_wt")
            with c_qty: st.number_input("Qty", min_value=1, step=1, key="input_qty")
            with c_type: st.number_input("Type (1=Plt, 2=Crt)", min_value=1, max_value=2, value=1, step=1, key="input_pack_type")
            st.button("Add to List", type="primary", use_container_width=True, on_click=add_item_callback)
            
            # --- JS INJECTION ---
            st.markdown("""
                <script>
                function setupEnterKeyNavigation() {
                    try {
                        const doc = window.parent.document;
                        const inputs = Array.from(doc.querySelectorAll('input')).filter(el => {
                                if (el.offsetParent === null) return false;
                                const type = el.getAttribute('type');
                                return ['text', 'number', 'password', 'search', 'tel', 'url'].includes(type) || !type;
                            });
                        inputs.forEach((input, index) => {
                            if (input._enterHandler) input.removeEventListener('keydown', input._enterHandler, true);
                            input._enterHandler = function(e) {
                                if (e.key === 'Enter') {
                                    e.preventDefault(); e.stopPropagation();
                                    const nextInput = inputs[index + 1];
                                    if (nextInput) { nextInput.focus(); nextInput.select(); } 
                                    else {
                                        const buttons = Array.from(doc.querySelectorAll('button')).filter(b => b.offsetParent !== null && b.innerText.includes("Add to List"));
                                        if (buttons.length > 0) { buttons[buttons.length - 1].click(); }
                                    }
                                }
                            };
                            input.addEventListener('keydown', input._enterHandler, true);
                        });
                    } catch (e) { console.log(e); }
                }
                setInterval(setupEnterKeyNavigation, 1000);
                </script>
                """, unsafe_allow_html=True)
            
            if st.session_state['should_focus_desc']:
                st.markdown("""<script>setTimeout(function() { var doc = window.parent.document; var input = doc.querySelector('input[aria-label="Description"]'); if (input) { input.focus(); } }, 100);</script>""", unsafe_allow_html=True)
                st.session_state['should_focus_desc'] = False

        if len(st.session_state['container_items']) > 0:
            df_container = pd.DataFrame(st.session_state['container_items'])
            if "Delete" not in df_container.columns: df_container["Delete"] = False
            if "Type" not in df_container.columns: df_container["Type"] = 1
            edited_container_df = st.data_editor(
                df_container, num_rows="fixed", use_container_width=True,
                column_config={
                    "Delete": st.column_config.CheckboxColumn("❌", width="small"),
                    "Description": st.column_config.TextColumn("Item"),
                    "Weight (kg)": st.column_config.NumberColumn("Wt", format="%.1f"),
                    "Length (mm)": st.column_config.NumberColumn("L", format="%d"),
                    "Width (mm)": st.column_config.NumberColumn("W", format="%d"),
                    "Height (mm)": st.column_config.NumberColumn("H", format="%d"),
                    "Qty": st.column_config.NumberColumn("Qty", step=1),
                    "Type": st.column_config.NumberColumn("Type", min_value=1, max_value=2, step=1, width="small")
                },
                column_order=("Delete", "Description", "Weight (kg)", "Length (mm)", "Width (mm)", "Height (mm)", "Qty", "Type"), 
                hide_index=True, key="container_list_editor"
            )
            if edited_container_df['Delete'].any():
                edited_container_df = edited_container_df[~edited_container_df['Delete']]
                edited_container_df['Delete'] = False
                st.session_state['container_items'] = edited_container_df.to_dict('records')
                st.rerun()
            else:
                st.session_state['container_items'] = edited_container_df.to_dict('records')
        else:
            st.info("Packing list is empty.")

        if st.button("🚀 Calculate Loading Plan", type="primary", use_container_width=True):
            st.session_state["manual_select"] = None
            st.session_state["last_chart_sel"] = []
            st.session_state["last_table_sel"] = []
            with st.spinner("AI is optimizing placement and balancing weight..."):
                items_data = []
                for item in st.session_state['container_items']:
                    if item.get("Length (mm)") and item.get("Weight (kg)"):
                        raw_type = item.get("Type", 1)
                        try: p_type_val = int(raw_type)
                        except: p_type_val = 1
                        items_data.append({
                            "name": item.get("Description", "Item"),
                            "l": item["Length (mm)"], "w": item["Width (mm)"], "h": item["Height (mm)"],
                            "weight": item["Weight (kg)"], "qty": item["Qty"], "packaging_type": p_type_val
                        })
                
                # --- CONNECT TO OPTIMIZER ---
                if items_data:
                    container = optimizer.solve_packing(
                        container_l=cont_l, container_w=cont_w, container_h=cont_h, 
                        items_data=items_data, allow_stacking=enable_stacking_flag, min_gap=min_gap_val
                    )
                    st.session_state['container_plan'] = container
                else:
                    st.warning("⚠️ List is empty or missing dimensions.")
            st.rerun()

        # --- MANUAL ADJUSTMENT & HUD CONTROLLER ---
        if st.session_state.get('container_plan'):
            container_res = st.session_state['container_plan']
            
            item_options = [f"P_{i} | {item.name}" for i, item in enumerate(container_res.items)]
            unpacked_options = [f"U_{i} | {item.name}" for i, item in enumerate(container_res.unpacked_items)]
            all_options = item_options + unpacked_options
            
            if "manual_select" not in st.session_state: 
                st.session_state["manual_select"] = None
            
            selected_option = st.session_state.get("manual_select")
            if selected_option and selected_option not in all_options:
                selected_option = None
                st.session_state["manual_select"] = None
            
            highlight_name = None
            if selected_option:
                try:
                    parts = selected_option.split(" | ")
                    highlight_name = parts[1]
                    type_code, str_idx = parts[0].split("_")
                    idx = int(str_idx)
                    
                    is_unpacked = (type_code == "U")
                    item_to_edit = container_res.unpacked_items[idx] if is_unpacked else container_res.items[idx]
                    dims = item_to_edit.get_dimension()
                    
                    # FAULT TOLERANT SLIDER BOUNDARY FIX:
                    # Guarantees the slider NEVER crashes due to invalid dimensions
                    item_x = float(getattr(item_to_edit, 'x', 0.0))
                    item_y = float(getattr(item_to_edit, 'y', 0.0))
                    item_z = float(getattr(item_to_edit, 'z', 0.0))

                    raw_max_x = float(container_res.L - dims[0])
                    raw_max_y = float(container_res.W - dims[1])
                    raw_max_z = float(container_res.H - dims[2])

                    # Force minimum maximums of 10.0 to prevent StreamlitAPIException crashes
                    safe_max_x = max(10.0, raw_max_x)
                    safe_max_y = max(10.0, raw_max_y)
                    safe_max_z = max(10.0, raw_max_z)

                    curr_x = max(0.0, min(item_x, safe_max_x))
                    curr_y = max(0.0, min(item_y, safe_max_y))
                    curr_z = max(0.0, min(item_z, safe_max_z))

                    with st.container():
                        st.markdown('<div id="hud-marker"></div>', unsafe_allow_html=True)
                        
                        status_badge = "⚠️ UNPACKED (GHOST)" if is_unpacked else "✅ PACKED"
                        status_color = "#facc15" if is_unpacked else "#4ade80"
                        st.markdown(f'<div class="hud-title">{item_to_edit.name}<br><span style="font-size:0.7em;color:{status_color};">{status_badge}</span></div>', unsafe_allow_html=True)
                        
                        def update_hud_prop(item, axis, key):
                            val = st.session_state[key]
                            if axis == 'x': item.x = val
                            elif axis == 'y': item.y = val
                            elif axis == 'z': item.z = val
                        
                        # --- X, Y, Z CONTROLS WITH SAFE BOUNDARIES ---
                        st.markdown('<div class="hud-label">Position</div>', unsafe_allow_html=True)
                        
                        cx1, cx2 = st.columns([3, 1])
                        with cx1: st.slider("X", min_value=0.0, max_value=safe_max_x, value=curr_x, step=10.0, key=f"slide_x_{type_code}_{idx}", label_visibility="collapsed", on_change=update_hud_prop, args=(item_to_edit, 'x', f"slide_x_{type_code}_{idx}"))
                        with cx2: st.number_input("X Val", min_value=0.0, max_value=safe_max_x, value=curr_x, step=10.0, key=f"inp_x_{type_code}_{idx}", label_visibility="collapsed", on_change=update_hud_prop, args=(item_to_edit, 'x', f"inp_x_{type_code}_{idx}"))
                        
                        cy1, cy2 = st.columns([3, 1])
                        with cy1: st.slider("Y", min_value=0.0, max_value=safe_max_y, value=curr_y, step=10.0, key=f"slide_y_{type_code}_{idx}", label_visibility="collapsed", on_change=update_hud_prop, args=(item_to_edit, 'y', f"slide_y_{type_code}_{idx}"))
                        with cy2: st.number_input("Y Val", min_value=0.0, max_value=safe_max_y, value=curr_y, step=10.0, key=f"inp_y_{type_code}_{idx}", label_visibility="collapsed", on_change=update_hud_prop, args=(item_to_edit, 'y', f"inp_y_{type_code}_{idx}"))
                        
                        cz1, cz2 = st.columns([3, 1])
                        with cz1: st.slider("Z", min_value=0.0, max_value=safe_max_z, value=curr_z, step=10.0, key=f"slide_z_{type_code}_{idx}", label_visibility="collapsed", on_change=update_hud_prop, args=(item_to_edit, 'z', f"slide_z_{type_code}_{idx}"))
                        with cz2: st.number_input("Z Val", min_value=0.0, max_value=safe_max_z, value=curr_z, step=10.0, key=f"inp_z_{type_code}_{idx}", label_visibility="collapsed", on_change=update_hud_prop, args=(item_to_edit, 'z', f"inp_z_{type_code}_{idx}"))

                        st.markdown('<div class="hud-label">Controls</div>', unsafe_allow_html=True)
                        
                        # UNPACKED CONTROLS vs PACKED CONTROLS
                        if is_unpacked:
                            c_btn1, c_btn2, c_btn3 = st.columns(3)
                            with c_btn1:
                                if st.button("🔄 Rot 90°", key=f"rot_{type_code}_{idx}", use_container_width=True):
                                    item_to_edit.rotation = 1 if item_to_edit.rotation == 0 else 0
                                    dims = item_to_edit.get_dimension()
                                    if item_to_edit.x + dims[0] > container_res.L: item_to_edit.x = container_res.L - dims[0]
                                    if item_to_edit.y + dims[1] > container_res.W: item_to_edit.y = container_res.W - dims[1]
                                    st.rerun()
                            with c_btn2:
                                if st.button("⬇️ Auto Drop", key=f"drop_{idx}", type="primary", use_container_width=True):
                                    packed_item = container_res.drop_unpacked_item(idx, item_to_edit.x, item_to_edit.y)
                                    if packed_item:
                                        st.session_state["manual_select"] = f"P_{len(container_res.items)-1} | {packed_item.name}"
                                        st.session_state["last_table_sel"] = []
                                        st.session_state["last_chart_sel"] = []
                                    st.rerun()
                            with c_btn3:
                                if st.button("📦 Pack", key=f"pack_{idx}", type="secondary", use_container_width=True):
                                    packed_item = container_res.force_pack_item(idx, item_to_edit.x, item_to_edit.y, item_to_edit.z)
                                    if packed_item:
                                        st.session_state["manual_select"] = f"P_{len(container_res.items)-1} | {packed_item.name}"
                                        st.session_state["last_table_sel"] = []
                                        st.session_state["last_chart_sel"] = []
                                    st.rerun()
                        else:
                            c_btn1, c_btn2 = st.columns(2)
                            with c_btn1:
                                if st.button("🔄 Rotate 90°", key=f"rot_{type_code}_{idx}", use_container_width=True):
                                    item_to_edit.rotation = 1 if item_to_edit.rotation == 0 else 0
                                    dims = item_to_edit.get_dimension()
                                    if item_to_edit.x + dims[0] > container_res.L: item_to_edit.x = container_res.L - dims[0]
                                    if item_to_edit.y + dims[1] > container_res.W: item_to_edit.y = container_res.W - dims[1]
                                    st.rerun()
                            with c_btn2:
                                if st.button("📤 Unpack", key=f"unpack_{idx}", type="primary", use_container_width=True):
                                    moved_item = container_res.items.pop(idx)
                                    container_res.unpacked_items.append(moved_item)
                                    container_res.current_weight -= moved_item.weight
                                    st.session_state["manual_select"] = f"U_{len(container_res.unpacked_items)-1} | {moved_item.name}"
                                    st.session_state["last_table_sel"] = []
                                    st.session_state["last_chart_sel"] = []
                                    st.rerun()

                        if st.button("Close Controls", key=f"cls_{type_code}_{idx}", type="secondary", use_container_width=True):
                            st.session_state["manual_select"] = None
                            st.session_state["last_chart_sel"] = []
                            st.session_state["last_table_sel"] = []
                            st.rerun()
                except Exception as e:
                    st.error(f"HUD Render Error: {str(e)}")

    # --- RIGHT: VISUALIZATION ---
    with row1_col2:
        container = st.session_state.get('container_plan')
        if container:
            stats = optimizer.get_container_stats(container)
            
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            kpi1.metric("Packed", f"{stats['packed_count']} / {stats['packed_count'] + stats['unpacked_count']}")
            kpi2.metric("Weight", f"{stats['weight_total']:,.0f} kg")
            kpi3.metric("Vol %", f"{stats['volume_utilization']:.1f}%")
            
            bal = stats['balance_ratio_len']
            delta_color = "normal" if 45 <= bal <= 55 else "inverse"
            kpi4.metric("Long. Bal", f"{bal:.0f}%", delta="Target 50%", delta_color=delta_color)

            # 3D Chart
            try:
                fig = optimizer.visualize_container(container, highlight_name=highlight_name)
            except TypeError:
                fig = optimizer.visualize_container(container)
            
            fig.update_layout(clickmode='event+select', hovermode='closest')
            event = st.plotly_chart(fig, use_container_width=True, theme="streamlit", on_select="rerun", selection_mode="points", key="3d_chart_v2")
            
            # --- OVERRIDE PROTECTION: Process Chart Clicks ---
            current_chart_sel = []
            if event and hasattr(event, "selection") and event.selection and "points" in event.selection:
                current_chart_sel = event.selection["points"]
                
            if current_chart_sel != st.session_state.get("last_chart_sel"):
                st.session_state["last_chart_sel"] = current_chart_sel
                if current_chart_sel:
                    try:
                        point = current_chart_sel[0]
                        if "customdata" in point:
                            ref_id = point["customdata"]
                            if isinstance(ref_id, list): ref_id = ref_id[0]
                            target_val = None
                            if ref_id.startswith("P_"):
                                idx = int(ref_id.split("_")[1])
                                if 0 <= idx < len(container.items): target_val = f"{ref_id} | {container.items[idx].name}"
                            elif ref_id.startswith("U_"):
                                idx = int(ref_id.split("_")[1])
                                if 0 <= idx < len(container.unpacked_items): target_val = f"{ref_id} | {container.unpacked_items[idx].name}"
                                    
                            if target_val and st.session_state.get("manual_select") != target_val:
                                st.session_state["manual_select"] = target_val
                                st.rerun()
                    except: pass

            # ==============================================================
            # COMBINED INTERACTIVE TABLE
            # ==============================================================
            st.caption("📋 **Click a row below to select item:**")
            list_data = []
            
            # Add Packed Items
            for i, item in enumerate(container.items):
                list_data.append({
                    "Ref": f"P_{i}", "Status": "✅ Inside", "Name": item.name, 
                    "Dim": f"{item.l:.0f}x{item.w:.0f}x{item.h:.0f}", 
                    "Pos": f"({getattr(item, 'x', 0):.0f}, {getattr(item, 'y', 0):.0f}, {getattr(item, 'z', 0):.0f})"
                })
                
            # Add Unpacked Items
            for i, item in enumerate(container.unpacked_items):
                list_data.append({
                    "Ref": f"U_{i}", "Status": "❌ Not Inside", "Name": item.name, 
                    "Dim": f"{item.l:.0f}x{item.w:.0f}x{item.h:.0f}", 
                    "Pos": f"({getattr(item, 'x', 0):.0f}, {getattr(item, 'y', 0):.0f}, {getattr(item, 'z', 0):.0f})"
                })
                
            df_items = pd.DataFrame(list_data)
            selection = st.dataframe(
                df_items, use_container_width=True, hide_index=True, 
                on_select="rerun", selection_mode="single-row", key="item_table",
                column_config={"Ref": None}
            )
            
            # --- OVERRIDE PROTECTION: Process Table Clicks ---
            current_table_sel = []
            if selection and hasattr(selection, "selection") and hasattr(selection.selection, "rows"):
                current_table_sel = selection.selection.rows
                
            if current_table_sel != st.session_state.get("last_table_sel"):
                st.session_state["last_table_sel"] = current_table_sel
                if current_table_sel:
                    row_idx = current_table_sel[0]
                    selected_ref = list_data[row_idx]["Ref"]
                    selected_name = list_data[row_idx]["Name"]
                    
                    target_val = f"{selected_ref} | {selected_name}"
                    if st.session_state.get("manual_select") != target_val:
                        st.session_state["manual_select"] = target_val
                        st.rerun()

            st.subheader("⚖️ Weight Balance")
            b1, b2, b3 = st.columns(3)
            with b1:
                len_f = stats['balance_ratio_len']; len_b = 100 - len_f
                st.metric("Longitudinal", f"{len_f:.0f}% / {len_b:.0f}%", help="Front / Back")
                st.progress(min(1.0, max(0.0, len_f / 100)))
            with b2:
                wid_l = stats['balance_ratio_width']; wid_r = 100 - wid_l
                st.metric("Horizontal", f"{wid_l:.0f}% / {wid_r:.0f}%", help="Left / Right")
                st.progress(min(1.0, max(0.0, wid_l / 100)))
            with b3:
                hgt_b = stats['balance_ratio_height']; hgt_t = 100 - hgt_b
                st.metric("Vertical", f"{hgt_b:.0f}% / {hgt_t:.0f}%", help="Bottom / Top")
                st.progress(min(1.0, max(0.0, hgt_b / 100)))

            if stats['unpacked_count'] > 0:
                st.error(f"⚠️ {stats['unpacked_count']} items could not fit! Check the 'Not Inside' items in the table above.")
        else:
            st.markdown("""<div style="display:flex; justify-content:center; align-items:center; height:400px; border: 2px dashed #334155; border-radius: 10px; color: #64748b;"><div style="text-align:center"><h3>👈 Step 1: Input List</h3><p>Step 2: Click <b>'Calculate Loading Plan'</b></p></div></div>""", unsafe_allow_html=True)