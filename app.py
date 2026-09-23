from __future__ import annotations

from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import analyse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
if not (DATA_DIR / "nodes.parquet").exists():
    downloaded_data = Path.home() / "Downloads" / "data (1)" / "data"
    if (downloaded_data / "nodes.parquet").exists():
        DATA_DIR = downloaded_data

TEXT = {
    "Русский": {
        "title": "Alem Trace", "subtitle": "Приоритеты проверки по графу переводов",
        "question": "Кого из 2 248 клиентов смотреть первым и почему?",
        "period": "Период анализа", "clients": "Клиентов", "links": "Связей",
        "volume": "Оборот внутри графа", "boundary": "Узлы на границе 4-го колена",
        "queue": "Очередь проверки", "search": "Найти клиента по GID",
        "role_filter": "Роль", "all": "Все роли", "client": "Карточка клиента",
        "network": "Связи клиента", "cluster": "Кластер", "score": "Приоритет",
        "confidence": "Уверенность в роли", "why": "Почему эта роль",
        "inflow": "Получено", "outflow": "Отправлено", "payers": "Плательщики",
        "receivers": "Получатели", "transactions": "Переводы", "download": "Скачать CSV",
        "exports": "Выгрузки", "roles": "Роли клиентов", "clusters": "Кластеры",
        "top": "Топ приоритетов", "run": "Пересчитать данные", "upload": "Загрузить свои 3 parquet-файла",
        "review_tab": "Проверка клиентов", "cluster_tab": "Кластеры и сигналы", "method_tab": "Методика",
        "role_mix": "Распределение ролей", "selected_cluster": "Разбор кластера",
        "stat_note": "Разведочное сравнение ролей внутри кластера и вне его",
        "no_test": "Сравнение пропущено: нужны не менее 15 узлов в кластере и хотя бы один узел за его пределами.",
        "nodes_word": "узлов", "role_col": "Роль", "inside_share": "Доля в кластере", "outside_share": "Доля вне кластера",
        "or_label": "OR / q", "ci_low": "95% ДИ нижняя", "ci_high": "95% ДИ верхняя", "p_label": "p", "q_label": "q (BH)",
        "log_or_axis": "log₂ OR  ·  0 = без отличия от остальной сети", "seed_label": "Seed",
        "method_text": "Приоритет = 30% оценка роли + 25% оборот + 20% посредничество + 15% число контрагентов + 10% близость к seed. Это порядок ручного просмотра, не вероятность риска.",
        "test_text": "Для кластеров от 15 узлов доли всех функциональных ролей сравниваются с остальной сетью точным тестом Фишера. OR и приближённый 95% интервал используют поправку 0,5 для нулевых ячеек. Поправка Benjamini–Hochberg применяется ко всем проверкам; q < 0,05, OR > 1 и не менее 3 случаев роли обозначают разведочный сигнал.",
        "caveat_text": "Роли и кластеры построены по одному графу, поэтому статистика не является независимым подтверждением гипотезы. Она помогает выбрать направление проверки; подтверждение требует проверки первичных операций или другого периода.",
        "upload_help": "Выберите nodes.parquet, edges.parquet и transactions.parquet вместе.",
        "upload_help": "Выберите nodes.parquet, edges.parquet и transactions.parquet вместе.",
        "scope": "Это очередь для анализа, а не вывод о нарушении. Показатели основаны только на переводах внутри загруженного графа.",
        "truncated": "Обход остановлен на 4-м колене: отсутствие исходящих связей в файле не доказывает, что клиент конечный получатель.",
        "seed": "Для seed-клиентов входящие переводы извне выборки не видны.",
        "no_data": "Не удалось разобрать данные. Проверьте названия и состав parquet-файлов.",
    },
    "Қазақша": {
        "title": "Alem Trace", "subtitle": "Аударымдар желісі бойынша тексеру кезегі",
        "question": "2 248 клиенттің қайсысын бірінші тексеру керек және неге?",
        "period": "Талдау кезеңі", "clients": "Клиенттер", "links": "Байланыстар",
        "volume": "Желі ішіндегі айналым", "boundary": "4-деңгей шекарасындағы түйіндер",
        "queue": "Тексеру кезегі", "search": "GID бойынша клиентті табу",
        "role_filter": "Рөл", "all": "Барлық рөлдер", "client": "Клиент карточкасы",
        "network": "Клиент байланыстары", "cluster": "Топ", "score": "Басымдық",
        "confidence": "Рөл сенімділігі", "why": "Бұл рөл неге берілді",
        "inflow": "Қабылдады", "outflow": "Жіберді", "payers": "Төлеушілер",
        "receivers": "Алушылар", "transactions": "Аударымдар", "download": "CSV жүктеу",
        "exports": "Экспорттар", "roles": "Клиент рөлдері", "clusters": "Топтар",
        "top": "Басым клиенттер", "run": "Деректерді қайта есептеу", "upload": "3 parquet файлын жүктеу",
        "review_tab": "Клиенттерді тексеру", "cluster_tab": "Топтар мен сигналдар", "method_tab": "Әдістеме",
        "role_mix": "Рөлдердің таралуы", "selected_cluster": "Топты талдау",
        "stat_note": "Топ ішіндегі және одан тыс рөлдерді барлау салыстыруы",
        "no_test": "Салыстыру жасалмады: топта кемінде 15 түйін және оның сыртында кемінде бір түйін болуы керек.",
        "nodes_word": "түйін", "role_col": "Рөл", "inside_share": "Топ ішіндегі үлес", "outside_share": "Топтан тыс үлес",
        "or_label": "OR / q", "ci_low": "95% аралық төменгі шек", "ci_high": "95% аралық жоғарғы шек", "p_label": "p", "q_label": "q (BH)",
        "log_or_axis": "log₂ OR  ·  0 = желінің қалған бөлігінен айырмашылық жоқ", "seed_label": "Seed",
        "method_text": "Басымдық = рөл бағасы 30% + айналым 25% + делдалдық 20% + контрагенттер саны 15% + seed-ке жақындық 10%. Бұл тек қолмен тексеру кезегі, тәуекел ықтималдығы емес.",
        "test_text": "15 немесе одан көп түйіні бар топтарда барлық функционалдық рөлдердің үлесі желінің қалған бөлігімен Фишердің дәл тесті арқылы салыстырылады. Нөлдік ұяшықтарға 0,5 түзетуі қолданылады. Benjamini–Hochberg барлық тексеруге қолданылады; q < 0,05, OR > 1 және кемінде 3 жағдай — барлау сигналы.",
        "caveat_text": "Рөлдер мен топтар бір графтан есептелген, сондықтан статистика гипотезаның тәуелсіз дәлелі емес. Ол тек тексеру бағытын таңдауға көмектеседі; растау үшін бастапқы операцияларды немесе басқа кезеңді қарау керек.",
        "upload_help": "nodes.parquet, edges.parquet және transactions.parquet файлдарын бірге таңдаңыз.",
        "scope": "Бұл талдау кезегі, құқық бұзушылық туралы қорытынды емес. Көрсеткіштер тек жүктелген желідегі аударымдарға негізделген.",
        "truncated": "Іздеу 4-деңгейде тоқтады: файлда шығыс байланысының болмауы клиенттің соңғы алушы екенін дәлелдемейді.",
        "seed": "Бастапқы seed-клиенттерге желіден тыс түскен аударымдар көрінбейді.",
        "no_data": "Деректерді оқу мүмкін болмады. Parquet файлдарының атауы мен құрамын тексеріңіз.",
    },
    "English": {
        "title": "Alem Trace", "subtitle": "Review queue from the transfer graph",
        "question": "Which of the 2,248 clients should be reviewed first, and why?",
        "period": "Analysis period", "clients": "Clients", "links": "Connections",
        "volume": "Volume inside graph", "boundary": "Nodes at the 4th-hop boundary",
        "queue": "Review queue", "search": "Find client by GID",
        "role_filter": "Role", "all": "All roles", "client": "Client profile",
        "network": "Client connections", "cluster": "Cluster", "score": "Priority",
        "confidence": "Role confidence", "why": "Why this role",
        "inflow": "Received", "outflow": "Sent", "payers": "Payers",
        "receivers": "Recipients", "transactions": "Transfers", "download": "Download CSV",
        "exports": "Exports", "roles": "Client roles", "clusters": "Clusters",
        "top": "Top priorities", "run": "Recalculate data", "upload": "Upload your 3 parquet files",
        "review_tab": "Client review", "cluster_tab": "Clusters and signals", "method_tab": "Method",
        "role_mix": "Role distribution", "selected_cluster": "Cluster detail",
        "stat_note": "Exploratory comparison of roles inside and outside the cluster",
        "no_test": "Comparison skipped: a cluster needs at least 15 nodes and at least one node outside it.",
        "nodes_word": "nodes", "role_col": "Role", "inside_share": "Share in cluster", "outside_share": "Share outside",
        "or_label": "OR / q", "ci_low": "95% CI low", "ci_high": "95% CI high", "p_label": "p", "q_label": "q (BH)",
        "log_or_axis": "log₂ OR  ·  0 = no difference from the rest of the graph", "seed_label": "Seeds",
        "method_text": "Priority = 30% role score + 25% flow volume + 20% betweenness + 15% counterparty count + 10% seed proximity. It is a manual review order, not a probability of risk.",
        "test_text": "For clusters of 15+ nodes, all functional role shares are compared with the rest of the graph using Fisher's exact test. A 0.5 correction handles zero cells in the OR and approximate 95% interval. Benjamini–Hochberg adjusts all tests; q < 0.05, OR > 1, and at least 3 role cases mark an exploratory signal.",
        "caveat_text": "Roles and clusters come from the same graph, so these statistics are not independent confirmation. They help direct review; confirmation requires transaction-level evidence or another time period.",
        "upload_help": "Select nodes.parquet, edges.parquet, and transactions.parquet together.",
        "scope": "This is a review queue, not a finding of wrongdoing. Metrics use only transfers visible in the uploaded graph.",
        "truncated": "Traversal stopped at hop 4: no outgoing edge in this file does not prove the client is a terminal recipient.",
        "seed": "Incoming transfers from outside this sample are not visible for seed clients.",
        "no_data": "Could not read the data. Check parquet file names and columns.",
    },
}
ROLE_NAMES = {
    "Русский": {"consolidator": "Консолидация", "transit": "Транзит", "distributor": "Распределение", "terminal": "Конечный получатель", "coordinator": "Связующий узел", "peripheral": "Периферия"},
    "Қазақша": {"consolidator": "Шоғырландыру", "transit": "Транзит", "distributor": "Тарату", "terminal": "Соңғы алушы", "coordinator": "Байланыстырушы түйін", "peripheral": "Шеткі түйін"},
    "English": {"consolidator": "Consolidator", "transit": "Transit", "distributor": "Distributor", "terminal": "Terminal recipient", "coordinator": "Coordinator", "peripheral": "Peripheral"},
}
COLORS = {"consolidator": "#D1495B", "transit": "#00798C", "distributor": "#EDAe49", "terminal": "#30638E", "coordinator": "#6A994E", "peripheral": "#8A8F98"}


def get_result(uploaded):
    if not uploaded:
        source = DATA_DIR
    else:
        expected = {"edges.parquet", "nodes.parquet", "transactions.parquet"}
        files = {item.name: item for item in uploaded}
        if set(files) != expected:
            st.error("Нужны ровно три файла: edges.parquet, nodes.parquet, transactions.parquet")
            return None
        source = {name: item.getvalue() for name, item in files.items()}
    try:
        result = analyse(source)
        return result
    except Exception as error:
        st.error(f"{TEXT[st.session_state.language]['no_data']} ({error})")
        return None


def fmt_money(value: float) -> str:
    return f"{value:,.0f} ₸"


def explain(row: pd.Series, language: str) -> str:
    names = ROLE_NAMES[language]
    if language == "Русский":
        return row.evidence
    if row.role == "consolidator":
        text = f"Получает от {row.in_deg} клиентов {fmt_money(row.in_kzt)}; удерживает около {row.retained_share:.0%} видимого входящего потока." if language == "Қазақша" else f"Receives from {row.in_deg} clients {fmt_money(row.in_kzt)}; retains about {row.retained_share:.0%} of visible inflow."
    elif row.role == "transit":
        text = f"Қабылдағаны {fmt_money(row.in_kzt)}, жібергені {fmt_money(row.out_kzt)}; ағын қатынасы {row.pass_through:.2f}." if language == "Қазақша" else f"Received {fmt_money(row.in_kzt)} and sent {fmt_money(row.out_kzt)}; flow ratio {row.pass_through:.2f}."
    elif row.role == "distributor":
        text = f"{row.out_deg} алушыға {fmt_money(row.out_kzt)} жіберді; аударым саны: {row.out_tx}." if language == "Қазақша" else f"Sent {fmt_money(row.out_kzt)} to {row.out_deg} recipients in {row.out_tx} transfers."
    elif row.role == "terminal":
        text = f"{row.in_deg} клиенттен {fmt_money(row.in_kzt)} қабылдады; шығыс байланысы жоқ, тереңдігі {row.depth}." if language == "Қазақша" else f"Received {fmt_money(row.in_kzt)} from {row.in_deg} clients; no outgoing edge, depth {row.depth}."
    elif row.role == "coordinator":
        text = f"Көп қатысушыны байланыстырады: {row.in_deg} кіріс және {row.out_deg} шығыс байланыс; делдалдық көрсеткіші жоғары." if language == "Қазақша" else f"Connects many participants with {row.in_deg} incoming and {row.out_deg} outgoing links; high betweenness."
    else:
        text = f"Айқын құрылымдық рөл табылмады; тереңдігі {row.depth}, кіріс байланыс {row.in_deg}, шығыс байланыс {row.out_deg}." if language == "Қазақша" else f"No strong structural role found; depth {row.depth}, {row.in_deg} incoming and {row.out_deg} outgoing links."
    if row.truncated_by_depth:
        note = " Іздеу 4-деңгейде тоқтады; соңғы алушы екені белгісіз." if language == "Қазақша" else " Traversal stopped at hop 4; terminal status is unknown."
        text += note
    elif row.is_seed and row.role in ("transit", "distributor"):
        text += " Seed-клиенттің кіріс ағыны толық емес." if language == "Қазақша" else " Incoming seed-client flow is incomplete."
    return f"{names[row.role]}: {text}"


def draw_network(g: nx.DiGraph, nodes: pd.DataFrame, gid: int):
    neighbors = set(g.predecessors(gid)) | set(g.successors(gid)) | {gid}
    sub = g.subgraph(neighbors).copy()
    if len(sub) > 55:
        ranked = sorted((n for n in neighbors if n != gid),
                        key=lambda n: g[gid][n]["sum_kzt"] if g.has_edge(gid, n) else g[n][gid]["sum_kzt"], reverse=True)
        keep = set(ranked[:54]) | {gid}
        sub = g.subgraph(keep).copy()
    pos = nx.spring_layout(sub, seed=8, weight="sum_kzt", k=1.0 / max(1, len(sub) ** 0.5))
    edge_x, edge_y, arrow_annotations = [], [], []
    for src, dst, data in sub.edges(data=True):
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
        arrow_annotations.append(dict(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                                      showarrow=True, arrowhead=2, arrowsize=0.8, arrowwidth=1,
                                      arrowcolor="#9BA3AA", opacity=0.7))
    node_frame = nodes.set_index("gid")
    xs, ys, colors, sizes, labels, hover = [], [], [], [], [], []
    for node in sub.nodes:
        row = node_frame.loc[node]
        xs.append(pos[node][0]); ys.append(pos[node][1]); labels.append(str(node)[-6:])
        colors.append(COLORS[row.role]); sizes.append(22 if node == gid else 13)
        hover.append(f"GID {node}<br>{row.role}<br>Приоритет {row.priority_score:.2f}<br>Входящих: {row.in_deg} · Исходящих: {row.out_deg}")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=1, color="#B8C0C8"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=labels, textposition="top center",
                             hovertext=hover, hoverinfo="text", marker=dict(size=sizes, color=colors,
                             line=dict(width=1, color="white"))))
    fig.update_layout(height=390, margin=dict(l=0, r=0, t=5, b=0), showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False), plot_bgcolor="white",
                      annotations=arrow_annotations)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


st.set_page_config(page_title="Alem Trace", page_icon="◉", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1480px; padding-top: 1.6rem; padding-bottom: 2rem;}
[data-testid="stMetric"] {background: #f3f6f6; border-left: 3px solid #00798c; padding: .65rem .8rem; border-radius: 3px;}
[data-testid="stMetricLabel"] {color: #58636a; font-size: .78rem;}
[data-testid="stMetricValue"] {color: #20292e; font-size: 1.35rem;}
[data-testid="stDataFrame"] {border: 1px solid #e3e8ea; border-radius: 4px;}
.stTabs [data-baseweb="tab-list"] {gap: .5rem; border-bottom: 1px solid #dce3e5;}
.stTabs [data-baseweb="tab"] {height: 2.8rem; padding: 0 .9rem;}
</style>
""", unsafe_allow_html=True)
if "language" not in st.session_state:
    st.session_state.language = "Русский"
with st.sidebar:
    language = st.selectbox("Language / Тіл / Язык", list(TEXT), index=list(TEXT).index(st.session_state.language))
    st.session_state.language = language
    t = TEXT[language]
    uploaded = st.file_uploader(t["upload"], type=["parquet"], accept_multiple_files=True, help=t["upload_help"])
    if st.button(t["run"], use_container_width=True):
        st.session_state.pop("result", None)
if "result" not in st.session_state:
    with st.spinner("Анализирую граф…"):
        st.session_state.result = get_result(uploaded)
result = st.session_state.result
if result is None:
    st.stop()

df, g, edges = result["nodes"], result["graph"], result["edges"]
head, selector = st.columns([0.74, 0.26], vertical_alignment="center")
with head:
    st.title(t["title"])
    st.caption(t["subtitle"])
with selector:
    st.caption(t["scope"])
st.markdown(f"<div style='font-size:1.12rem;font-weight:650;margin:.25rem 0 1rem;color:#20292e'>{t['question']}</div>", unsafe_allow_html=True)
dates = result["transactions"].date
period = f"{dates.min():%d.%m.%Y} — {dates.max():%d.%m.%Y}"
total = float(edges.sum_kzt.sum())
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(t["period"], period); c2.metric(t["clients"], f"{len(df):,}".replace(",", " "))
c3.metric(t["links"], f"{len(edges):,}".replace(",", " ")); c4.metric(t["volume"], fmt_money(total))
c5.metric(t["boundary"], int(df.truncated_by_depth.sum()))
role_names = ROLE_NAMES[language]
review_tab, cluster_tab, method_tab = st.tabs([t["review_tab"], t["cluster_tab"], t["method_tab"]])

with review_tab:
    left, right = st.columns([1.08, 1], gap="large")
    with left:
        st.subheader(t["queue"])
        selected_role = st.selectbox(t["role_filter"], [t["all"]] + list(role_names.values()))
        queue = df.nlargest(50, "priority_score")[["gid", "role", "priority_score", "evidence"]].copy()
        if selected_role != t["all"]:
            raw_role = next(role for role, name in role_names.items() if name == selected_role)
            queue = df[df.role == raw_role].nlargest(50, "priority_score")[["gid", "role", "priority_score", "evidence"]].copy()
        queue["rank"] = df.priority_score.rank(method="min", ascending=False).reindex(queue.index).astype(int)
        queue["role"] = queue.role.map(role_names)
        queue["why"] = queue.gid.map(lambda item: explain(df.loc[df.gid == item].iloc[0], language))
        queue["priority_score"] = queue.priority_score.map(lambda value: round(float(value), 3))
        st.dataframe(queue[["rank", "gid", "role", "priority_score", "why"]], hide_index=True,
                     use_container_width=True, height=470,
                     column_config={"rank": st.column_config.NumberColumn("#", width="small"),
                                    "gid": st.column_config.NumberColumn("GID", width="medium"),
                                    "priority_score": st.column_config.ProgressColumn(t["score"], min_value=0, max_value=1, format="%.3f")})
        export_cols = st.columns(3)
        exports = [("top_nodes.csv", t["top"], result["top_nodes"]),
                   ("nodes_roles.csv", t["roles"], result["nodes_roles"]),
                   ("clusters.csv", t["clusters"], result["clusters"])]
        for col, (filename, label, frame) in zip(export_cols, exports):
            col.download_button(f"{t['download']} · {label}", frame.to_csv(index=False).encode("utf-8-sig"),
                                file_name=filename, mime="text/csv", key=filename, use_container_width=True)
    with right:
        st.subheader(t["client"])
        gid_text = st.text_input(t["search"], value=str(int(queue.iloc[0].gid)) if len(queue) else "")
        try:
            gid = int(gid_text)
        except ValueError:
            gid = -1
        if gid not in set(df.gid):
            st.info("GID не найден в текущем наборе данных." if language == "Русский" else
                    "GID деректерден табылмады." if language == "Қазақша" else "GID not found in this dataset.")
        else:
            row = df.loc[df.gid == gid].iloc[0]
            a, b, c = st.columns(3)
            a.metric(t["score"], f"{row.priority_score:.3f}"); b.metric(t["confidence"], f"{row.role_score:.2f}")
            c.metric(t["cluster"], int(row.cluster_id))
            st.markdown(f"**{role_names[row.role]}** · GID `{gid}`")
            st.write(explain(row, language))
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(t["inflow"], fmt_money(row.in_kzt)); m2.metric(t["outflow"], fmt_money(row.out_kzt))
            m3.metric(t["payers"], int(row.in_deg)); m4.metric(t["receivers"], int(row.out_deg))
            if row.truncated_by_depth:
                st.warning(t["truncated"])
            elif row.is_seed:
                st.info(t["seed"])
            st.subheader(t["network"])
            draw_network(g, df, gid)

with cluster_tab:
    clusters = result["clusters"]
    st.subheader(t["clusters"])
    cluster_ids = clusters.cluster_id.astype(int).tolist()
    selected_cluster = st.selectbox(t["selected_cluster"], cluster_ids,
                                    format_func=lambda cid: f"#{cid} · {int(clusters.loc[clusters.cluster_id == cid, 'n_nodes'].iloc[0])} {t['nodes_word']}")
    cluster_row = clusters.loc[clusters.cluster_id == selected_cluster].iloc[0]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(t["clients"], int(cluster_row.n_nodes)); k2.metric(t["seed_label"], int(cluster_row.n_seed))
    k3.metric(t["volume"], fmt_money(cluster_row.sum_kzt_internal))
    k4.metric(t["or_label"], f"{cluster_row.odds_ratio:.2f} / {cluster_row.q_value:.3g}" if pd.notna(cluster_row.q_value) else "—")
    st.markdown(f"**{t['stat_note']}**")
    st.write(cluster_row.hypothesis)
    stats = result["cluster_role_stats"]
    stats = stats[stats.cluster_id == selected_cluster].copy()
    if stats.empty:
        st.info(t["no_test"])
    else:
        stats["role_name"] = stats.role.map(role_names)
        fig = go.Figure()
        for _, item in stats.iterrows():
            y = np.log2(item.odds_ratio)
            fig.add_trace(go.Scatter(x=[y], y=[item.role_name], mode="markers",
                                     marker=dict(size=10, color="#00798C" if item.q_value < 0.05 and item.odds_ratio > 1 else "#8A8F98"),
                                     error_x=dict(type="data", symmetric=False,
                                                  array=[np.log2(item.ci95_high) - y],
                                                  arrayminus=[y - np.log2(item.ci95_low)],
                                                  color="#74828A", thickness=1.4, width=4),
                                     hovertemplate=f"OR {item.odds_ratio:.2f}<br>95% CI {item.ci95_low:.2f}–{item.ci95_high:.2f}<br>q={item.q_value:.3g}<extra></extra>"))
        fig.add_vline(x=0, line_dash="dash", line_color="#7a858b", line_width=1)
        fig.update_layout(height=300, margin=dict(l=5, r=18, t=10, b=25), showlegend=False,
                          xaxis_title=t["log_or_axis"],
                          yaxis_title=None, plot_bgcolor="white", xaxis=dict(showgrid=True, gridcolor="#edf0f1"))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        stats_view = stats[["role_name", "cluster_role_share", "outside_role_share", "odds_ratio", "ci95_low", "ci95_high", "p_value", "q_value"]].rename(columns={
            "role_name": t["role_col"], "cluster_role_share": t["inside_share"], "outside_role_share": t["outside_share"],
            "odds_ratio": "OR", "ci95_low": t["ci_low"], "ci95_high": t["ci_high"], "p_value": t["p_label"], "q_value": t["q_label"]})
        st.dataframe(stats_view, hide_index=True, use_container_width=True,
                     column_config={t["inside_share"]: st.column_config.NumberColumn(format="percent"),
                                    t["outside_share"]: st.column_config.NumberColumn(format="percent")})
    cluster_view = clusters[["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "signal_role", "odds_ratio", "q_value"]].copy()
    cluster_view["sum_kzt_internal"] = cluster_view.sum_kzt_internal.map(fmt_money)
    cluster_view["signal_role"] = cluster_view.signal_role.map(lambda role: role_names.get(role, "—"))
    st.dataframe(cluster_view, hide_index=True, use_container_width=True, height=300)

with method_tab:
    st.subheader(t["role_mix"])
    role_counts = df.role.value_counts().reindex(ROLE_NAMES[language], fill_value=0)
    role_fig = go.Figure(go.Bar(x=role_counts.values, y=[role_names[r] for r in role_counts.index],
                                orientation="h", marker_color=[COLORS[r] for r in role_counts.index],
                                text=role_counts.values, textposition="outside", cliponaxis=False))
    role_fig.update_layout(height=300, margin=dict(l=5, r=35, t=5, b=10),
                           xaxis_title=t["clients"], yaxis_title=None, plot_bgcolor="white",
                           xaxis=dict(showgrid=True, gridcolor="#edf0f1"))
    st.plotly_chart(role_fig, use_container_width=True, config={"displayModeBar": False})
    st.subheader(t["score"])
    st.info(t["method_text"])
    st.subheader(t["stat_note"])
    st.write(t["test_text"])
    st.caption(t["caveat_text"])
