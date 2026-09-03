import streamlit as st
import pandas as pd
from datetime import datetime
from ortools.sat.python import cp_model

st.set_page_config(page_title="Genomics Task Scheduler", layout="wide")
st.title("Daily Shift & Task Scheduler")

# --- HELPER FUNCTIONS ---
def color_categories(row):
    cat = row.get("Category", "")
    # Soft background colors with dark text for readability
    color_map = {
        "Sample processing": "background-color: #d0e1fd; color: #000;",  # Blue
        "Quality": "background-color: #fef3c7; color: #000;",            # Yellow
        "Maintenance": "background-color: #f3e8ff; color: #000;"         # Purple
    }
    return [color_map.get(cat, "")] * len(row)

# --- 1. DATA UPLOAD ---
st.markdown("### Upload Master Schedule Data")
uploaded_file = st.file_uploader("Upload your master Excel file with Workers, Tasks, and Skills tabs", type=["xlsx"])

if uploaded_file is not None:
    # Read the three tabs from the uploaded Excel file
    workers_df = pd.read_excel(uploaded_file, sheet_name="Workers")
    tasks_df = pd.read_excel(uploaded_file, sheet_name="Tasks")
    skills_df = pd.read_excel(uploaded_file, sheet_name="Skills")
    
    # Force the empty Assigned_To column to accept text strings
    if "Assigned_To" in tasks_df.columns:
        tasks_df["Assigned_To"] = tasks_df["Assigned_To"].astype("object")

    if "Required_Shift" not in tasks_df.columns:
        tasks_df["Required_Shift"] = "Any"
    
    # Set the index of the skills matrix to the worker's name for easy lookup
    skills_df.set_index("Worker_Name", inplace=True)
    worker_names = workers_df["Worker_Name"].tolist()

    # --- 2. TOP CONTROLS ---
    st.markdown("---")
    days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    current_day = datetime.now().strftime("%a") 
    selected_day = st.selectbox("Select Day of the Week", days_of_week, index=days_of_week.index(current_day) if current_day in days_of_week else 0)

    # Look at the specific day's column in Excel sheet to auto-check the roster
    if selected_day in workers_df.columns:
        workers_df["Working_Today?"] = workers_df[selected_day] == True
    else:
        st.warning(f"Your Workers tab is missing a column named '{selected_day}'")
        workers_df["Working_Today?"] = False

    # --- 3. INTERACTIVE TABLES ---
    col1, col2 = st.columns([1, 1.5]) 

    with col1:
        st.subheader(f"1. Roster for {selected_day}")
        edited_workers = st.data_editor(
            workers_df[["Working_Today?", "Worker_Name", "Start_Time", "End_Time"]],
            hide_index=True, key="worker_editor", use_container_width=True
        )

    with col2:
        st.subheader("2. Today's Task Load")
        edited_tasks = st.data_editor(
            tasks_df,
            column_config={
                "Assigned_To": st.column_config.SelectboxColumn("Manual Override", options=worker_names),
                "Override_Quantity": st.column_config.NumberColumn("Override Qty", min_value=0, step=1),
                "Required_Shift": st.column_config.SelectboxColumn("Shift", options=["Any", "AM", "PM"]),
                "Priority": st.column_config.CheckboxColumn("Priority"),
                "Duration_Hours": st.column_config.NumberColumn("Hours/Task", min_value=0.1, step=0.1),
                "Default_Quantity": st.column_config.NumberColumn("Quantity Needed", min_value=0, step=1),
                "Category": None
            },
            hide_index=True, key="task_editor", use_container_width=True,
            num_rows="dynamic"
        )

    st.markdown("---")

    # --- 4. THE OPTIMIZATION SOLVER ---
    if st.button("Generate Today's Schedule", type="primary"):
        present_workers = edited_workers[edited_workers["Working_Today?"] == True].copy()
        
        if present_workers.empty:
            st.error("No one is working today!")
        else:
            model = cp_model.CpModel()
            
            # --- Capacity Setup (Hard 100% Limit, Soft 80% Target) ---
            worker_limits = {}
            for _, row in present_workers.iterrows():
                start_str = str(row["Start_Time"])
                end_str = str(row["End_Time"])
                
                fmt = "%H:%M:%S" if len(start_str.split(":")) == 3 else "%H:%M"
                
                t1 = datetime.strptime(start_str, fmt)
                t2 = datetime.strptime(end_str, fmt)
                total_hours = (t2 - t1).total_seconds() / 3600
                
                is_am_worker = t1.hour < 12  # Starts before noon
                is_pm_worker = t2.hour >= 14 # Ends at 2:00 PM or later
                
                hard_limit_mins = int(total_hours * 60)
                target_limit_mins = int(hard_limit_mins * 0.8)
                
                worker_limits[row["Worker_Name"]] = {
                    "hard": hard_limit_mins,
                    "target": target_limit_mins,
                    "is_am": is_am_worker,
                    "is_pm": is_pm_worker
                }
                
            active_worker_names = list(worker_limits.keys())
            
            # --- Task Setup ---
            task_instances = []
            for _, row in edited_tasks.iterrows():
                total_qty = int(row["Default_Quantity"])
                
                override_worker = None
                if "Assigned_To" in edited_tasks.columns and pd.notna(row["Assigned_To"]):
                    override_worker = row["Assigned_To"]
                
                override_qty = 0
                if "Override_Quantity" in edited_tasks.columns and pd.notna(row["Override_Quantity"]):
                    override_qty = int(row["Override_Quantity"])
                
                override_qty = min(override_qty, total_qty)
                
                task_category = row.get("Category", "General")
                
                for i in range(total_qty):
                    current_override = override_worker if i < override_qty else None
                    
                    task_instances.append({
                        "id": f"{row['Task_Name']} #{i+1}",
                        "name": row['Task_Name'],
                        "category": task_category,
                        "duration_mins": int(row["Duration_Hours"] * 60),
                        "priority": bool(row["Priority"]),
                        "override": current_override,
                        "required_shift": row.get("Required_Shift", "Any")
                    })
                    
            x = {}
            for worker in active_worker_names:
                for task in task_instances:
                    skill_val = skills_df.get(task["name"], pd.Series()).get(worker, False)
                    is_trained = skill_val in [True, 1, "TRUE", "True"]
                    
                    req_shift = task["required_shift"]
                    worker_am = worker_limits[worker]["is_am"]
                    worker_pm = worker_limits[worker]["is_pm"]
                    
                    shift_match = True
                    if req_shift == "AM" and not worker_am:
                        shift_match = False
                    if req_shift == "PM" and not worker_pm:
                        shift_match = False
                    
                    if (is_trained and shift_match) or task["override"] == worker:
                        x[(worker, task["id"])] = model.NewBoolVar(f"assign_{worker}_{task['id']}")
                        
            # --- Constraint 1: At most one person per task (Allows partial schedule) ---
            for task in task_instances:
                valid_workers = [w for w in active_worker_names if (w, task["id"]) in x]
                if task["override"] and task["override"] in valid_workers:
                    model.Add(x[(task["override"], task["id"])] == 1)
                    for w in valid_workers:
                        if w != task["override"]:
                            model.Add(x[(w, task["id"])] == 0)
                else:
                    if valid_workers:
                        model.AddAtMostOne(x[(w, task["id"])] for w in valid_workers)

            # --- Constraint 2: Capacity & Soft Target Penalties ---
            objective_terms = []
            worker_total_mins = {}
            
            for worker in active_worker_names:
                assigned_mins = []
                for task in task_instances:
                    if (worker, task["id"]) in x:
                        assigned_mins.append(x[(worker, task["id"])] * task["duration_mins"])
                
                if assigned_mins:
                    total_assigned = sum(assigned_mins)
                    worker_total_mins[worker] = total_assigned
                    hard_limit = worker_limits[worker]["hard"]
                    target_limit = worker_limits[worker]["target"]
                    
                    # HARD LIMIT: Cannot exceed shift total
                    model.Add(total_assigned <= hard_limit)
                    
                    # SOFT LIMIT PENALTY: Penalty for work over 80%
                    over_target = model.NewIntVar(0, hard_limit, f"over_{worker}")
                    model.Add(over_target >= total_assigned - target_limit)
                    objective_terms.append(-2 * over_target)

            # --- Workload Balancing ---
            if len(active_worker_names) > 1:
                max_mins = model.NewIntVar(0, 1440, "max_load")
                min_mins = model.NewIntVar(0, 1440, "min_load")
                
                load_vars = list(worker_total_mins.values())
                if load_vars:
                    model.AddMaxEquality(max_mins, load_vars)
                    model.AddMinEquality(min_mins, load_vars)
                    load_spread = model.NewIntVar(0, 1440, "load_spread")
                    model.Add(load_spread == max_mins - min_mins)
                    objective_terms.append(-5 * load_spread)

            # --- Maximization Objective: Heavy Priority Weighting ---
            for worker in active_worker_names:
                for task in task_instances:
                    if (worker, task["id"]) in x:
                        # Priority tasks are worth 100,000 pts; Normal tasks are worth 1,000 pts
                        weight = 100000 if task["priority"] else 1000
                        objective_terms.append(x[(worker, task["id"])] * weight)
                        
            model.Maximize(sum(objective_terms))
            
            # --- Solve ---
            solver = cp_model.CpSolver()
            status = solver.Solve(model)
            
            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                st.success("Schedule successfully optimized!")
                results = []
                unscheduled_tasks = []
                
                for task in task_instances:
                    assigned = False
                    for worker in active_worker_names:
                        if (worker, task["id"]) in x and solver.Value(x[(worker, task["id"])]) == 1:
                            results.append({
                                "Worker": worker,
                                "Assigned Task": task["name"],
                                "Category": task["category"],
                                "Duration (Hrs)": task["duration_mins"] / 60
                            })
                            assigned = True
                            break
                    if not assigned:
                        unscheduled_tasks.append({
                            "Task Name": task["name"],
                            "Category": task["category"],
                            "Priority": "Yes" if task["priority"] else "No",
                            "Duration (Hrs)": task["duration_mins"] / 60
                        })
                
                # Pop-up / Notification for unscheduled tasks
                if unscheduled_tasks:
                    unscheduled_df = pd.DataFrame(unscheduled_tasks)
                    summary = unscheduled_df.groupby(["Task Name", "Category", "Priority", "Duration (Hrs)"]).size().reset_index(name="Unassigned Qty")
                    
                    st.warning("⚠️ **Notice: Some tasks could not be scheduled due to capacity or skill limits.**")
                    with st.expander("📋 View List of Unscheduled Tasks", expanded=True):
                        st.dataframe(
                            summary, 
                            hide_index=True, 
                            use_container_width=True,
                            column_config={"Category": None}
                        )

                if results:
                    results_df = pd.DataFrame(results)
                    
                    st.markdown("### 📊 Shift Summary Dashboard")
                    metric_cols = st.columns(len(active_worker_names))
                    
                    for idx, worker in enumerate(active_worker_names):
                        worker_tasks = results_df[results_df["Worker"] == worker]
                        total_hrs = worker_tasks["Duration (Hrs)"].sum() if not worker_tasks.empty else 0
                        utilization = int((total_hrs / (worker_limits[worker]["hard"] / 60)) * 100) if worker_limits[worker]["hard"] > 0 else 0
                        
                        with metric_cols[idx]:
                            st.metric(label=worker, value=f"{total_hrs} hrs", delta=f"{utilization}% capacity")
                    
                    st.markdown("---")
                    st.markdown("### 📋 Individual Task Breakdown")
                    
                    worker_tabs = st.tabs(active_worker_names)
                    for idx, worker in enumerate(active_worker_names):
                        with worker_tabs[idx]:
                            worker_tasks = results_df[results_df["Worker"] == worker]
                            if not worker_tasks.empty:
                                styled_table = worker_tasks[["Assigned Task", "Category", "Duration (Hrs)"]].style.apply(color_categories, axis=1)
                                st.dataframe(
                                    styled_table, 
                                    hide_index=True, 
                                    use_container_width=True,
                                    column_config={"Category": None}
                                )
                            else:
                                st.info("No tasks assigned for this shift.")
                else:
                    st.warning("No tasks could be assigned to any active worker.")
            else:
                st.error("No valid schedule found. Check your manual assignments and total capacities.")
else:
    st.info("Please upload your Excel file to begin.")
