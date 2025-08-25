import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import os
import datetime
import logging
import bcrypt

# --- Configuration ---
# Use st.secrets for Streamlit Cloud deployment
try:
    db_conf = st.secrets["database"]
    log_conf = st.secrets["logging"]
except KeyError as e:
    st.error(f"Missing configuration in `st.secrets`: {e}. Please configure your Streamlit Cloud secrets.")
    st.stop()


# --- Logging Setup ---
@st.cache_resource
def setup_logging():
    """Sets up and returns a logger instance."""
    log_dir = log_conf.get("log_dir", "logs")
    log_file = log_conf.get("log_file", "app.log")

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_path = os.path.join(log_dir, log_file)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger


logger = setup_logging()


# --- Database Engine Creation ---
@st.cache_resource
def get_db_engine():
    """Creates and caches the database engine."""
    encoded_password = quote_plus(db_conf["password"])
    db_uri = (
        f"mysql+pymysql://{db_conf['user']}:{encoded_password}@"
        f"{db_conf['host']}:{db_conf['port']}/{db_conf['name']}?charset=utf8mb4"
    )
    try:
        engine = create_engine(db_uri)
        logger.info("Database engine created successfully.")
        return engine
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        st.error(f"Database connection failed: {e}")
        st.stop()


engine = get_db_engine()

# --- Session State Initialization ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""


# --- Login, Logout, and Auth Functions ---
def login():
    """Renders the login page."""
    st.title("🔐 登录系统")
    username = st.text_input("用户名")
    password = st.text_input("密码", type="password")

    if st.button("登录"):
        if not username or not password:
            st.error("用户名和密码不能为空。")
            return

        with engine.connect() as conn:
            user_query = text("SELECT username, password_hash, role FROM users WHERE username = :username")
            user_data = conn.execute(user_query, {"username": username}).fetchone()

        if user_data:
            db_username, db_hash, db_role = user_data
            try:
                if bcrypt.checkpw(password.encode('utf-8'), db_hash.encode('utf-8')):
                    st.session_state.logged_in = True
                    st.session_state.username = db_username
                    st.session_state.role = db_role
                    st.success("登录成功！")
                    logger.info(f"用户 '{db_username}' 登录成功，角色为 '{db_role}'")
                    st.rerun()
                else:
                    st.error("用户名或密码错误")
                    logger.warning(f"用户尝试登录失败：用户名 '{username}'，密码不正确")
            except Exception as e:
                st.error("用户名或密码错误")
                logger.error(f"用户 '{username}' 密码验证失败：{e}")
        else:
            st.error("用户名或密码错误")
            logger.warning(f"用户尝试登录失败：用户名 '{username}'，用户不存在")


def logout():
    """Logs out the current user."""
    logger.info(f"用户 '{st.session_state.username}' 退出登录")
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.rerun()


def login_check():
    """Checks login status and renders the main app or login page."""
    if st.session_state.logged_in:
        main_app()
    else:
        login()


# --- Main App Functions ---
def main_app():
    """Main application layout for logged-in users."""
    st.sidebar.write(f"👤 **当前用户：** {st.session_state.username} ({st.session_state.role})")
    if st.sidebar.button("退出登录"):
        logout()

    st.title("仪表盘")

    tabs = ["数据查询"]
    if st.session_state.role == "admin":
        tabs.append("数据写入")
        tabs.append("用户管理")

    selected_tab = st.tabs(tabs)

    if "数据查询" in selected_tab:
        with selected_tab[0]:
            data_query()

    if "数据写入" in selected_tab and st.session_state.role == "admin":
        with selected_tab[1]:
            data_write()

    if "用户管理" in selected_tab and st.session_state.role == "admin":
        with selected_tab[2]:
            user_management()


def get_tables():
    """Fetches a list of all tables from the database."""
    with engine.connect() as conn:
        result = conn.execute(text("SHOW TABLES"))
        return [row[0] for row in result.fetchall()]


def data_query():
    """Renders the data query section."""
    st.header("📊 数据查询")

    tables = get_tables()
    selected_table = st.selectbox("请选择数据表", tables)

    if not selected_table:
        st.info("请选择一个数据表进行查询。")
        return

    with st.spinner(f"正在获取表结构 {selected_table}..."):
        try:
            columns_df = pd.read_sql(text(f"SHOW COLUMNS FROM `{selected_table}`"), engine)
            cols = columns_df["Field"].tolist()
        except Exception as e:
            st.error(f"获取表列失败：{e}")
            logger.error(f"获取表 '{selected_table}' 的列失败：{e}")
            return

    date_cols = [c for c in cols if "date" in c.lower() or "time" in c.lower()]
    start_date, end_date, date_field = None, None, None
    if date_cols:
        st.subheader("时间范围筛选")
        date_field = st.selectbox("选择日期列", date_cols)
        today = datetime.date.today()
        default_start = today - datetime.timedelta(days=7)
        start_date, end_date = st.date_input(
            "选择时间范围",
            value=(default_start, today),
            format="YYYY-MM-DD"
        )
        if not isinstance(start_date, datetime.date) or not isinstance(end_date, datetime.date):
            st.warning("请选择有效的开始和结束日期。")
            return

    st.subheader("字段筛选")
    filterable_fields = [c for c in cols if c != date_field]
    filters = {}

    with st.expander("显示/隐藏筛选器"):
        for field in filterable_fields:
            try:
                unique_values = pd.read_sql(text(f"SELECT DISTINCT `{field}` FROM `{selected_table}` LIMIT 1000"),
                                            engine)
                options = unique_values[field].dropna().unique().tolist()
                selected_vals = st.multiselect(
                    f"按 '{field}' 筛选 (可多选)",
                    options=options,
                    default=[],
                    key=f"filter_{field}"
                )
                if selected_vals:
                    filters[field] = (selected_vals, "in_list")
            except Exception as e:
                st.warning(f"无法获取 '{field}' 的唯一值，将使用文本搜索：{e}")
                val = st.text_input(f"为 '{field}' 输入搜索文本 (模糊匹配)", key=f"text_filter_{field}")
                if val.strip():
                    filters[field] = (val.strip(), "like")

    where_clauses, params = [], {}
    if date_field and start_date and end_date:
        where_clauses.append(f"`{date_field}` BETWEEN :start_date AND :end_date")
        params["start_date"] = start_date.strftime("%Y-%m-%d")
        params["end_date"] = end_date.strftime("%Y-%m-%d")

    for field, (value, match_type) in filters.items():
        if match_type == "in_list" and value:
            placeholders = ', '.join([f':{field}_{i}' for i in range(len(value))])
            where_clauses.append(f"`{field}` IN ({placeholders})")
            for i, val in enumerate(value):
                params[f'{field}_{i}'] = val
        elif match_type == "like" and value:
            where_clauses.append(f"`{field}` LIKE :{field}")
            params[field] = f"%{value}%"

    where_sql = " AND ".join(where_clauses)
    query = f"SELECT * FROM `{selected_table}`"
    if where_sql:
        query += f" WHERE {where_sql}"
    query += " LIMIT 1000"

    if st.button("执行查询"):
        with st.spinner("正在获取数据..."):
            try:
                df = pd.read_sql(text(query), engine, params=params)
                st.write(f"查询结果（最多1000条） 共计 {len(df)} 行")

                if not df.empty:
                    display_data(df, selected_table, date_field)
                else:
                    st.info("根据所选筛选条件未找到数据。")
                logger.info(f"用户 '{st.session_state.username}' 成功查询表 '{selected_table}'。")
            except Exception as e:
                st.error(f"查询失败：{e}")
                logger.error(f"用户 '{st.session_state.username}' 查询表 '{selected_table}' 失败：{e}")


def display_data(df, selected_table, date_field):
    """Handles data display and download options."""
    st.subheader("查询结果")

    pivot_option = False
    if 'tag' in df.columns and 'value' in df.columns and date_field:
        pivot_option = st.checkbox(
            "将 'tag' 列转换为独立列 (Excel三维表格式)",
            value=False
        )

    if pivot_option:
        try:
            pivot_df = pd.pivot_table(
                df,
                index=date_field,
                columns='tag',
                values='value',
                aggfunc='first'
            ).reset_index()
            st.dataframe(pivot_df)
            csv_bytes = pivot_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 导出 CSV (三维表)",
                data=csv_bytes,
                file_name=f"{selected_table}_pivot_export.csv",
                mime="text/csv"
            )
        except Exception as e:
            st.error(f"透视表转换失败：{e}")
            st.warning("请确保查询结果中包含时间字段、'tag' 列和 'value' 列。")
            st.dataframe(df)
    else:
        st.dataframe(df)
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 导出 CSV",
            data=csv_bytes,
            file_name=f"{selected_table}_export.csv",
            mime="text/csv"
        )


def data_write():
    """Renders the data write section (Admin only)."""
    st.header("📝 数据写入（管理员权限）")
    tables = get_tables()
    selected_table = st.selectbox("选择要写入数据的表", tables)

    if not selected_table:
        st.info("请选择一个数据表。")
        return

    columns_df = pd.read_sql(text(f"SHOW COLUMNS FROM `{selected_table}`"), engine)

    with st.form("data_entry_form"):
        new_data = {}
        st.subheader(f"为 `{selected_table}` 输入新数据")
        for _, row in columns_df.iterrows():
            new_data[row["Field"]] = st.text_input(f"{row['Field']} ({row['Type']})")

        submit = st.form_submit_button("提交数据")
        if submit:
            if all(v.strip() == "" for v in new_data.values()):
                st.warning("⚠️ 不能提交空数据！")
            else:
                try:
                    pd.DataFrame([new_data]).to_sql(
                        selected_table, con=engine, if_exists="append", index=False
                    )
                    st.success("✅ 数据写入成功！")
                    logger.info(f"管理员 '{st.session_state.username}' 向表 '{selected_table}' 写入数据：{new_data}")
                except Exception as e:
                    st.error(f"写入失败：{e}")
                    logger.error(f"管理员 '{st.session_state.username}' 尝试向表 '{selected_table}' 写入数据失败：{e}")


def user_management():
    """Admin page for managing users."""
    st.header("👥 用户管理（管理员权限）")

    st.subheader("创建新用户")
    with st.form("new_user_form"):
        new_username = st.text_input("用户名")
        new_password = st.text_input("密码", type="password")
        new_role = st.selectbox("角色", ["user", "admin"])
        submit_user = st.form_submit_button("创建用户")

        if submit_user:
            if not new_username or not new_password:
                st.warning("用户名和密码不能为空。")
            else:
                try:
                    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

                    with engine.connect() as conn:
                        insert_query = text(
                            "INSERT INTO users (username, password_hash, role) VALUES (:username, :password_hash, :role)")
                        conn.execute(insert_query,
                                     {"username": new_username, "password_hash": password_hash, "role": new_role})
                        conn.commit()
                    st.success(f"用户 '{new_username}' 创建成功！")
                    logger.info(
                        f"管理员 '{st.session_state.username}' 创建新用户 '{new_username}'，角色为 '{new_role}'。")
                    st.rerun()
                except Exception as e:
                    st.error(f"创建用户失败：{e}")
                    logger.error(f"管理员 '{st.session_state.username}' 尝试创建用户 '{new_username}' 失败：{e}")

    st.markdown("---")

    st.subheader("现有用户列表")
    try:
        users_df = pd.read_sql(text("SELECT id, username, role, created_at FROM users"), engine)

        # 使用 st.columns 布局来展示用户列表
        for _, row in users_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([0.5, 1, 1, 2, 1])
            col1.write(f"**ID:** {row['id']}")
            col2.write(f"**用户名:** {row['username']}")
            col3.write(f"**角色:** {row['role']}")
            col4.write(f"**创建时间:** {row['created_at'].strftime('%Y-%m-%d %H:%M:%S')}")

            if st.session_state.username != row['username']:
                with col5:
                    if st.button("删除", key=f"delete_{row['id']}"):
                        try:
                            with engine.connect() as conn:
                                delete_query = text("DELETE FROM users WHERE id = :id")
                                conn.execute(delete_query, {"id": row['id']})
                                conn.commit()
                            st.success(f"用户 '{row['username']}' 已被删除。")
                            logger.info(
                                f"管理员 '{st.session_state.username}' 删除了用户 '{row['username']}' (ID: {row['id']})。")
                            st.rerun()
                        except Exception as e:
                            st.error(f"删除用户失败：{e}")
                            logger.error(
                                f"管理员 '{st.session_state.username}' 尝试删除用户 '{row['username']}' 失败：{e}")
            else:
                with col5:
                    st.write("（当前用户）")

    except Exception as e:
        st.error(f"无法加载用户列表：{e}")
        logger.error(f"管理员 '{st.session_state.username}' 无法加载用户列表：{e}")


# --- 主程序入口 ---
if __name__ == "__main__":
    login_check()
