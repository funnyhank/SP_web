import streamlit as st
import pandas as pd
# import yaml
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import os
import datetime
import logging

# # --- 配置初始化 ---
# config_path = os.path.join("conf", "databaseconfig.yaml")
# if not os.path.exists(config_path):
#     st.error("配置文件 databaseconfig.yaml 不存在！请创建并配置该文件。")
#     st.stop()
#
# with open(config_path, "r", encoding="utf-8") as f:
#     config = yaml.safe_load(f)
#
# db_conf = config["database"]
# users_conf = config["users"]
# log_conf = config["logging"]

# --- 配置初始化 ---
# Streamlit Cloud 会自动提供 st.secrets
try:
    db_conf = st.secrets["database"]
except KeyError:
    # 如果在本地运行，st.secrets 可能不存在，
    # 此时你可以选择使用硬编码配置或本地文件
    # 这里为了演示，我们直接退出
    st.error("无法读取数据库配置，请确保已在 Streamlit Cloud 上配置 Secrets！")
    st.stop()

# 因为用户列表不包含敏感信息且很少变动，我们可以直接在代码中定义
# 如果用户较多或需要动态管理，则需要另外考虑方案
users_conf = [
  {"username": "admin", "password": "SR123456", "role": "admin"},
  {"username": "user", "password": "123456SR", "role": "user"}
]

log_conf = st.secrets["logging"]

# --- 配置日志记录 ---
log_dir = log_conf.get("log_dir", "logs")
log_file = log_conf.get("log_file", "app.log")

if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_path = os.path.join(log_dir, log_file)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(log_path, encoding='utf-8')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# --- 创建数据库引擎 ---
encoded_password = quote_plus(db_conf["password"])
db_uri = (
    f"mysql+pymysql://{db_conf['user']}:{encoded_password}@"
    f"{db_conf['host']}:{db_conf['port']}/{db_conf['name']}?charset=utf8mb4"
)
try:
    engine = create_engine(db_uri)
    logger.info("数据库引擎创建成功。")
except Exception as e:
    logger.error(f"数据库连接失败：{e}")
    st.error(f"数据库连接失败：{e}")
    st.stop()

# --- 登录状态 ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""


# --- 登录页面 ---
def login():
    st.title("🔐 登录系统")
    username = st.text_input("用户名")
    password = st.text_input("密码", type="password")
    if st.button("登录"):
        for user in users_conf:
            if user["username"] == username and user["password"] == password:
                st.session_state.logged_in = True
                st.session_state.username = username
                st.session_state.role = user["role"]
                st.success("登录成功！")
                logger.info(f"用户 '{username}' 登录成功，角色为 '{user['role']}'")
                st.rerun()
        st.error("用户名或密码错误")
        logger.warning(f"用户尝试登录失败：用户名 '{username}'")


# --- 退出登录 ---
def logout():
    logger.info(f"用户 '{st.session_state.username}' 退出登录")
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.rerun()


# --- 主页面 ---
def main():
    st.sidebar.write(f"👤 当前用户：{st.session_state.username} （{st.session_state.role}）")
    if st.sidebar.button("退出登录"):
        logout()

    menu = ["数据查询"]
    if st.session_state.role == "admin":
        menu.append("数据写入")

    choice = st.sidebar.selectbox("功能选择", menu)

    if choice == "数据查询":
        data_query()
    elif choice == "数据写入" and st.session_state.role == "admin":
        data_write()


# --- 数据查询 ---
def data_query():
    st.subheader("📊 数据查询")

    with engine.connect() as conn:
        result = conn.execute(text("SHOW TABLES"))
        tables = [row[0] for row in result.fetchall()]

    selected_table = st.selectbox("请选择数据表", tables)

    if not selected_table:
        st.info("请选择一个数据表")
        return

    columns_df = pd.read_sql(text(f"SHOW COLUMNS FROM `{selected_table}`"), engine)
    cols = columns_df["Field"].tolist()

    date_cols = [c for c in cols if "date" in c.lower() or "time" in c.lower()]
    today = datetime.date.today()
    default_start = today - datetime.timedelta(days=1)
    default_end = today

    start_date, end_date = None, None
    if date_cols:
        st.markdown("### 时间范围筛选")
        start_date, end_date = st.date_input(
            "请选择时间范围",
            value=(default_start, default_end),
            format="YYYY-MM-DD"
        )
        if not isinstance(start_date, datetime.date) or not isinstance(end_date, datetime.date):
            st.warning("请正确选择开始和结束日期")
            return
        date_field = date_cols[0]
    else:
        date_field = None

    st.markdown("### 字段筛选")
    filterable_fields = [c for c in cols if c != date_field]
    selected_filter_fields = st.multiselect(
        "选择要筛选的字段",
        options=filterable_fields,
        default=[]
    )

    filters = {}
    for field in selected_filter_fields:
        try:
            # 优化：不再使用阈值，直接获取所有唯一值，让 st.multiselect 内置搜索来处理
            unique_values = pd.read_sql(
                text(f"SELECT DISTINCT `{field}` FROM `{selected_table}`"),
                engine
            )
            options = unique_values[field].tolist()

            selected_vals = st.multiselect(
                f"请选择字段 '{field}' 的筛选内容 (支持多选)",
                options=options,
                default=[]
            )
            if selected_vals:
                filters[field] = (selected_vals, "in_list")

        except Exception as e:
            st.warning(f"获取字段 '{field}' 的唯一值失败，将使用文本输入框：{e}")
            val = st.text_input(f"请输入字段 '{field}' 的筛选内容 (模糊匹配)")
            if val.strip():
                filters[field] = (val.strip(), "like")

    # 构造SQL
    where_clauses = []
    params = {}
    if date_field and start_date and end_date:
        where_clauses.append(f"`{date_field}` BETWEEN :start_date AND :end_date")
        params["start_date"] = start_date.strftime("%Y-%m-%d")
        params["end_date"] = end_date.strftime("%Y-%m-%d")

    for k, (v, match_type) in filters.items():
        if match_type == "in_list":
            if v:
                placeholders = ', '.join([f':{k}_{i}' for i in range(len(v))])
                where_clauses.append(f"`{k}` IN ({placeholders})")
                for i, val in enumerate(v):
                    params[f'{k}_{i}'] = val
        elif match_type == "like":
            if v:
                where_clauses.append(f"`{k}` LIKE :{k}")
                params[k] = f"%{v}%"

    where_sql = " AND ".join(where_clauses)
    sql = f"SELECT * FROM `{selected_table}`"
    if where_sql:
        sql += f" WHERE {where_sql}"
    sql += " LIMIT 1000"

    try:
        df = pd.read_sql(text(sql), engine, params=params)
        st.write(f"查询结果（最多1000条） 共计 {len(df)} 行")

        if not df.empty:
            st.subheader("数据展示格式")
            pivot_option = st.checkbox("将Tag列转换为独立列（Excel三维表格式）", value=False)

            if pivot_option and 'tag' in df.columns and 'value' in df.columns and date_field in df.columns:
                try:
                    pivot_df = pd.pivot_table(
                        df,
                        index=date_field,
                        columns='tag',
                        values='value',
                        aggfunc='first'
                    )
                    pivot_df = pivot_df.reset_index()
                    st.dataframe(pivot_df)

                    csv_bytes = pivot_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="📥 导出 CSV（三维表）",
                        data=csv_bytes,
                        file_name=f"{selected_table}_pivot_export.csv",
                        mime="text/csv"
                    )
                except Exception as e:
                    st.error(f"透视表转换失败：{e}")
                    st.warning("请确保查询结果中包含时间字段、tag列和value列。")
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

    except Exception as e:
        st.error(f"查询失败：{e}")
        logger.error(f"用户 '{st.session_state.username}' 查询表 '{selected_table}' 失败：{e}")


# --- 数据写入（仅管理员） ---
def data_write():
    st.subheader("📝 数据写入（管理员权限）")

    with engine.connect() as conn:
        result = conn.execute(text("SHOW TABLES"))
        tables = [row[0] for row in result.fetchall()]

    selected_table = st.selectbox("选择要写入数据的表", tables)

    if not selected_table:
        st.info("请选择一个数据表")
        return

    columns_df = pd.read_sql(text(f"SHOW COLUMNS FROM `{selected_table}`"), engine)

    with st.form("data_entry_form"):
        new_data = {}
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


# --- 主程序入口 ---
if not st.session_state.logged_in:
    login()
else:
    main()
