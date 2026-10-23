import os
import sqlite3
from datetime import datetime, date

from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__, template_folder="templates")

CAMINHO_BANCO = os.path.join(app.root_path, "estoque.db")

STATUS_PEDIDOS = ["Pendente", "Em preparo", "Pronto", "Entregue"]


def conectar_banco():
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def criar_tabelas():
    with conectar_banco() as conexao:
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS ingredientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                categoria TEXT NOT NULL,
                quantidade REAL NOT NULL,
                unidade TEXT NOT NULL,
                minimo REAL NOT NULL
            )
        """)

        conexao.execute("""
            CREATE TABLE IF NOT EXISTS movimentacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingrediente_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                quantidade REAL NOT NULL,
                data_hora TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ingrediente_id) REFERENCES ingredientes(id)
            )
        """)

        conexao.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente TEXT NOT NULL,
                telefone TEXT,
                descricao TEXT NOT NULL,
                data_pedido TEXT NOT NULL,
                data_entrega TEXT NOT NULL,
                valor_total REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Pendente'
            )
        """)

        conexao.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                descricao TEXT,
                preco_venda REAL NOT NULL DEFAULT 0,
                rendimento REAL NOT NULL DEFAULT 1
            )
        """)

        conexao.execute("""
            CREATE TABLE IF NOT EXISTS receita_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produto_id INTEGER NOT NULL,
                ingrediente_id INTEGER NOT NULL,
                quantidade REAL NOT NULL,
                FOREIGN KEY (produto_id)
                    REFERENCES produtos(id) ON DELETE CASCADE,
                FOREIGN KEY (ingrediente_id)
                    REFERENCES ingredientes(id),
                UNIQUE (produto_id, ingrediente_id)
            )
        """)

        # Migração segura: não remove nem recria pedidos existentes.
        colunas_pedidos = {
            coluna["name"]
            for coluna in conexao.execute(
                "PRAGMA table_info(pedidos)"
            ).fetchall()
        }

        if "estoque_baixado" not in colunas_pedidos:
            conexao.execute("""
                ALTER TABLE pedidos
                ADD COLUMN estoque_baixado INTEGER NOT NULL DEFAULT 0
            """)

        # Guarda os produtos e as quantidades de cada pedido.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS pedido_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id INTEGER NOT NULL,
                produto_id INTEGER NOT NULL,
                quantidade REAL NOT NULL CHECK (quantidade > 0),
                FOREIGN KEY (pedido_id)
                    REFERENCES pedidos(id) ON DELETE CASCADE,
                FOREIGN KEY (produto_id)
                    REFERENCES produtos(id)
            )
        """)


@app.route("/")
def inicio():
    with conectar_banco() as conexao:
        total_ingredientes = conexao.execute(
            "SELECT COUNT(*) FROM ingredientes"
        ).fetchone()[0]

        estoque_baixo = conexao.execute("""
            SELECT COUNT(*) FROM ingredientes
            WHERE quantidade <= minimo
        """).fetchone()[0]

        baixo_estoque = conexao.execute("""
            SELECT * FROM ingredientes
            WHERE quantidade <= minimo
            ORDER BY (minimo - quantidade) DESC, nome
        """).fetchall()

        historico = conexao.execute("""
            SELECT movimentacoes.*, ingredientes.nome, ingredientes.unidade
            FROM movimentacoes
            JOIN ingredientes
                ON ingredientes.id = movimentacoes.ingrediente_id
            ORDER BY movimentacoes.id DESC
            LIMIT 5
        """).fetchall()

        total_pedidos = conexao.execute("""
            SELECT COUNT(*) FROM pedidos
            WHERE status != 'Entregue'
        """).fetchone()[0]

        pedidos_hoje = conexao.execute("""
            SELECT COUNT(*) FROM pedidos
            WHERE data_entrega = ?
              AND status != 'Entregue'
        """, (date.today().isoformat(),)).fetchone()[0]

        total_produtos = conexao.execute(
            "SELECT COUNT(*) FROM produtos"
        ).fetchone()[0]

    return render_template(
        "index.html",
        total_ingredientes=total_ingredientes,
        estoque_baixo=estoque_baixo,
        baixo_estoque=baixo_estoque,
        historico=historico,
        total_pedidos=total_pedidos,
        pedidos_hoje=pedidos_hoje,
        total_produtos=total_produtos
    )


@app.route("/ingredientes", methods=["GET", "POST"])
def ingredientes():
    mensagem = ""

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        categoria = request.form.get("categoria", "").strip()
        unidade = request.form.get("unidade", "").strip()

        try:
            quantidade = float(
                request.form.get("quantidade", "").replace(",", ".")
            )
            minimo = float(
                request.form.get("minimo", "").replace(",", ".")
            )

            if not nome or not categoria or not unidade:
                raise ValueError("Preencha todos os campos.")

            if quantidade < 0 or minimo < 0:
                raise ValueError(
                    "As quantidades não podem ser negativas."
                )

        except ValueError as erro:
            mensagem = str(erro)
        else:
            with conectar_banco() as conexao:
                conexao.execute("""
                    INSERT INTO ingredientes
                    (nome, categoria, quantidade, unidade, minimo)
                    VALUES (?, ?, ?, ?, ?)
                """, (nome, categoria, quantidade, unidade, minimo))

            return redirect(url_for("ingredientes"))

    with conectar_banco() as conexao:
        lista_ingredientes = conexao.execute(
            "SELECT * FROM ingredientes ORDER BY nome"
        ).fetchall()

    return render_template(
        "ingredientes.html",
        ingredientes=lista_ingredientes,
        mensagem=mensagem
    )


@app.route("/movimentacoes", methods=["GET", "POST"])
def movimentacoes():
    mensagem = ""

    if request.method == "POST":
        try:
            ingrediente_id = int(
                request.form.get("ingrediente_id", "")
            )
            tipo = request.form.get("tipo", "").strip().lower()
            quantidade = float(
                request.form.get("quantidade", "").replace(",", ".")
            )

            if tipo not in ("entrada", "saida"):
                raise ValueError("Tipo de movimentação inválido.")

            if quantidade <= 0:
                raise ValueError(
                    "A quantidade deve ser maior que zero."
                )

            with conectar_banco() as conexao:
                ingrediente = conexao.execute(
                    "SELECT * FROM ingredientes WHERE id = ?",
                    (ingrediente_id,)
                ).fetchone()

                if ingrediente is None:
                    mensagem = "Ingrediente não encontrado."

                elif (
                    tipo == "saida"
                    and quantidade > ingrediente["quantidade"]
                ):
                    mensagem = "Estoque insuficiente para essa saída."

                else:
                    estoque_atual = float(ingrediente["quantidade"])

                    if tipo == "entrada":
                        novo_estoque = estoque_atual + quantidade
                        tipo_historico = "Entrada"
                    else:
                        novo_estoque = estoque_atual - quantidade
                        tipo_historico = "Saída"

                    data_hora = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    conexao.execute("""
                        UPDATE ingredientes
                        SET quantidade = ?
                        WHERE id = ?
                    """, (novo_estoque, ingrediente_id))

                    conexao.execute("""
                        INSERT INTO movimentacoes
                        (ingrediente_id, tipo, quantidade, data_hora)
                        VALUES (?, ?, ?, ?)
                    """, (
                        ingrediente_id,
                        tipo_historico,
                        quantidade,
                        data_hora
                    ))

                    return redirect(url_for("movimentacoes"))

        except (ValueError, TypeError, KeyError) as erro:
            mensagem = f"Confira os dados informados: {erro}"

        except Exception as erro:
            print("ERRO NA MOVIMENTAÇÃO:", repr(erro))
            mensagem = (
                "Erro ao registrar. Confira o terminal do Eclipse."
            )

    with conectar_banco() as conexao:
        lista_ingredientes = conexao.execute(
            "SELECT * FROM ingredientes ORDER BY nome"
        ).fetchall()

        historico = conexao.execute("""
            SELECT movimentacoes.*, ingredientes.nome, ingredientes.unidade
            FROM movimentacoes
            JOIN ingredientes
                ON ingredientes.id = movimentacoes.ingrediente_id
            ORDER BY movimentacoes.id DESC
        """).fetchall()

    return render_template(
        "movimentacoes.html",
        ingredientes=lista_ingredientes,
        historico=historico,
        mensagem=mensagem
    )


@app.route("/pedidos", methods=["GET", "POST"])
def pedidos():
    mensagem = ""

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()
        telefone = request.form.get("telefone", "").strip()
        descricao_extra = request.form.get("descricao", "").strip()
        data_pedido = request.form.get("data_pedido", "").strip()
        data_entrega = request.form.get("data_entrega", "").strip()
        valor_texto = request.form.get("valor_total", "0").strip()

        try:
            valor_total = float(valor_texto.replace(",", "."))

            if not cliente:
                raise ValueError("Informe o nome do cliente.")

            if not data_entrega:
                raise ValueError("Informe a data de entrega.")

            if valor_total < 0:
                raise ValueError("O valor não pode ser negativo.")

            if not data_pedido:
                data_pedido = date.today().isoformat()

            if data_entrega < data_pedido:
                raise ValueError(
                    "A data de entrega não pode ser anterior "
                    "à data do pedido."
                )

            # Lê os produtos selecionados no formulário.
            ids_produtos = request.form.getlist("produto_id[]")
            quantidades = request.form.getlist("quantidade_produto[]")
            itens_pedido = []

            with conectar_banco() as conexao:
                try:
                    for id_texto, quantidade_texto in zip(
                        ids_produtos, quantidades
                    ):
                        id_texto = id_texto.strip()
                        quantidade_texto = quantidade_texto.strip().replace(
                            ",", "."
                        )

                        # Permite deixar linhas extras vazias.
                        if not id_texto and not quantidade_texto:
                            continue

                        if not id_texto or not quantidade_texto:
                            raise ValueError(
                                "Complete o produto e a quantidade "
                                "em cada linha utilizada."
                            )

                        produto_id = int(id_texto)
                        quantidade = float(quantidade_texto)

                        if quantidade <= 0:
                            raise ValueError(
                                "A quantidade pedida deve ser maior que zero."
                            )

                        produto = conexao.execute("""
                            SELECT id, nome
                            FROM produtos
                            WHERE id = ?
                        """, (produto_id,)).fetchone()

                        if produto is None:
                            raise ValueError(
                                "Um dos produtos selecionados não existe."
                            )

                        itens_pedido.append({
                            "produto_id": produto_id,
                            "quantidade": quantidade,
                            "nome": produto["nome"]
                        })

                except (ValueError, TypeError):
                    raise ValueError(
                        "Confira os produtos e as quantidades do pedido."
                    )

                if not itens_pedido and not descricao_extra:
                    raise ValueError(
                        "Adicione pelo menos um produto ou uma descrição."
                    )

                partes_descricao = [
                    f'{item["quantidade"]:g} x {item["nome"]}'
                    for item in itens_pedido
                ]

                if descricao_extra:
                    partes_descricao.append(descricao_extra)

                descricao = " | ".join(partes_descricao)

                cursor = conexao.execute("""
                    INSERT INTO pedidos
                    (cliente, telefone, descricao, data_pedido,
                     data_entrega, valor_total, status, estoque_baixado)
                    VALUES (?, ?, ?, ?, ?, ?, 'Pendente', 0)
                """, (
                    cliente,
                    telefone,
                    descricao,
                    data_pedido,
                    data_entrega,
                    valor_total
                ))

                pedido_id = cursor.lastrowid

                for item in itens_pedido:
                    conexao.execute("""
                        INSERT INTO pedido_itens
                        (pedido_id, produto_id, quantidade)
                        VALUES (?, ?, ?)
                    """, (
                        pedido_id,
                        item["produto_id"],
                        item["quantidade"]
                    ))

            return redirect(url_for("pedidos"))

        except ValueError as erro:
            mensagem = str(erro)

        except sqlite3.Error as erro:
            print("ERRO AO CADASTRAR PEDIDO:", repr(erro))
            mensagem = (
                "Não foi possível salvar o pedido. "
                "Confira os dados e tente novamente."
            )

    with conectar_banco() as conexao:
        lista_pedidos = conexao.execute("""
            SELECT * FROM pedidos
            ORDER BY
                CASE WHEN status = 'Entregue' THEN 1 ELSE 0 END,
                data_entrega ASC,
                id DESC
        """).fetchall()

        produtos_disponiveis = conexao.execute("""
            SELECT id, nome, preco_venda, rendimento
            FROM produtos
            ORDER BY nome
        """).fetchall()

        itens_por_pedido = {}

        for pedido in lista_pedidos:
            itens_por_pedido[pedido["id"]] = conexao.execute("""
                SELECT pedido_itens.quantidade, produtos.nome
                FROM pedido_itens
                JOIN produtos
                    ON produtos.id = pedido_itens.produto_id
                WHERE pedido_itens.pedido_id = ?
                ORDER BY pedido_itens.id
            """, (pedido["id"],)).fetchall()

    return render_template(
        "pedidos.html",
        pedidos=lista_pedidos,
        status_pedidos=STATUS_PEDIDOS,
        mensagem=mensagem,
        hoje=date.today().isoformat(),
        produtos=produtos_disponiveis,
        itens_por_pedido=itens_por_pedido
    )


@app.route("/pedidos/status/<int:pedido_id>", methods=["POST"])
def atualizar_status_pedido(pedido_id):
    novo_status = request.form.get("status", "").strip()

    if novo_status not in STATUS_PEDIDOS:
        return "Status inválido.", 400

    try:
        with conectar_banco() as conexao:
            pedido = conexao.execute("""
                SELECT * FROM pedidos WHERE id = ?
            """, (pedido_id,)).fetchone()

            if pedido is None:
                return "Pedido não encontrado.", 404

            # Só calcula e desconta o estoque na primeira entrada
            # do pedido no status "Em preparo".
            if (
                novo_status == "Em preparo"
                and not pedido["estoque_baixado"]
            ):
                itens_pedido = conexao.execute("""
                    SELECT
                        pedido_itens.produto_id,
                        pedido_itens.quantidade AS quantidade_pedida,
                        produtos.nome AS produto_nome,
                        produtos.rendimento
                    FROM pedido_itens
                    JOIN produtos
                        ON produtos.id = pedido_itens.produto_id
                    WHERE pedido_itens.pedido_id = ?
                """, (pedido_id,)).fetchall()

                # Pedidos antigos sem produtos vinculados continuam
                # funcionando, mas não descontam estoque automaticamente.
                if itens_pedido:
                    consumo_por_ingrediente = {}

                    for item in itens_pedido:
                        rendimento = float(item["rendimento"] or 0)

                        if rendimento <= 0:
                            return (
                                f'O produto "{item["produto_nome"]}" '
                                "tem rendimento inválido. Corrija o cadastro.",
                                400
                            )

                        receita = conexao.execute("""
                            SELECT
                                receita_itens.ingrediente_id,
                                receita_itens.quantidade,
                                ingredientes.nome AS ingrediente_nome,
                                ingredientes.unidade,
                                ingredientes.quantidade AS estoque_atual
                            FROM receita_itens
                            JOIN ingredientes
                                ON ingredientes.id =
                                   receita_itens.ingrediente_id
                            WHERE receita_itens.produto_id = ?
                        """, (item["produto_id"],)).fetchall()

                        if not receita:
                            return (
                                f'O produto "{item["produto_nome"]}" '
                                "não tem receita cadastrada.",
                                400
                            )

                        for ingrediente in receita:
                            ingrediente_id = ingrediente["ingrediente_id"]

                            # A quantidade da receita corresponde ao
                            # rendimento cadastrado no produto.
                            consumo = (
                                float(ingrediente["quantidade"])
                                * float(item["quantidade_pedida"])
                                / rendimento
                            )

                            if ingrediente_id not in consumo_por_ingrediente:
                                consumo_por_ingrediente[ingrediente_id] = {
                                    "nome": ingrediente["ingrediente_nome"],
                                    "unidade": ingrediente["unidade"],
                                    "estoque": float(
                                        ingrediente["estoque_atual"]
                                    ),
                                    "necessario": 0.0
                                }

                            consumo_por_ingrediente[
                                ingrediente_id
                            ]["necessario"] += consumo

                    # Primeiro verifica todos os ingredientes. Assim,
                    # não há baixa parcial se algum estiver em falta.
                    faltas = []

                    for info in consumo_por_ingrediente.values():
                        if info["necessario"] > info["estoque"] + 1e-9:
                            faltas.append(
                                f'{info["nome"]}: precisa de '
                                f'{info["necessario"]:.2f} {info["unidade"]}, '
                                f'mas há {info["estoque"]:.2f} '
                                f'{info["unidade"]}.'
                            )

                    if faltas:
                        return (
                            "Estoque insuficiente. O pedido não foi "
                            "colocado em preparo. " + " ".join(faltas),
                            400
                        )

                    data_hora = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    for ingrediente_id, info in (
                        consumo_por_ingrediente.items()
                    ):
                        quantidade = info["necessario"]

                        conexao.execute("""
                            UPDATE ingredientes
                            SET quantidade = quantidade - ?
                            WHERE id = ?
                        """, (quantidade, ingrediente_id))

                        conexao.execute("""
                            INSERT INTO movimentacoes
                            (ingrediente_id, tipo, quantidade, data_hora)
                            VALUES (?, 'Saída', ?, ?)
                        """, (
                            ingrediente_id,
                            quantidade,
                            data_hora
                        ))

                    conexao.execute("""
                        UPDATE pedidos
                        SET estoque_baixado = 1
                        WHERE id = ?
                    """, (pedido_id,))

            conexao.execute("""
                UPDATE pedidos
                SET status = ?
                WHERE id = ?
            """, (novo_status, pedido_id))

    except sqlite3.Error as erro:
        print("ERRO AO ATUALIZAR PEDIDO:", repr(erro))
        return (
            "Ocorreu um erro ao atualizar o pedido. "
            "Confira o terminal do Eclipse.",
            500
        )

    return redirect(url_for("pedidos"))


@app.route("/produtos", methods=["GET", "POST"])
def produtos():
    mensagem = ""

    with conectar_banco() as conexao:
        lista_ingredientes = conexao.execute(
            "SELECT * FROM ingredientes ORDER BY nome"
        ).fetchall()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        descricao = request.form.get("descricao", "").strip()

        try:
            preco_venda = float(
                request.form.get("preco_venda", "").replace(",", ".")
            )
            rendimento = float(
                request.form.get("rendimento", "").replace(",", ".")
            )

            ids_ingredientes = request.form.getlist("ingrediente_id")
            quantidades = request.form.getlist(
                "quantidade_ingrediente"
            )

            if not nome:
                raise ValueError("Informe o nome do produto.")

            if preco_venda < 0:
                raise ValueError("O preço não pode ser negativo.")

            if rendimento <= 0:
                raise ValueError(
                    "O rendimento deve ser maior que zero."
                )

            itens_receita = []
            ingredientes_vistos = set()

            for ingrediente_id_texto, quantidade_texto in zip(
                ids_ingredientes, quantidades
            ):
                if not ingrediente_id_texto and not quantidade_texto:
                    continue

                if not ingrediente_id_texto or not quantidade_texto:
                    raise ValueError(
                        "Complete o ingrediente e a quantidade "
                        "em cada linha utilizada."
                    )

                ingrediente_id = int(ingrediente_id_texto)
                quantidade = float(
                    quantidade_texto.replace(",", ".")
                )

                if quantidade <= 0:
                    raise ValueError(
                        "As quantidades da receita devem ser maiores que zero."
                    )

                if ingrediente_id in ingredientes_vistos:
                    raise ValueError(
                        "Selecione cada ingrediente apenas uma vez por receita."
                    )

                ingredientes_vistos.add(ingrediente_id)
                itens_receita.append((ingrediente_id, quantidade))

            if not itens_receita:
                raise ValueError(
                    "Adicione pelo menos um ingrediente à receita."
                )

            ids_validos = {
                int(item["id"]) for item in lista_ingredientes
            }

            for ingrediente_id, _ in itens_receita:
                if ingrediente_id not in ids_validos:
                    raise ValueError(
                        "Um dos ingredientes selecionados não existe."
                    )

            with conectar_banco() as conexao:
                cursor = conexao.execute("""
                    INSERT INTO produtos
                    (nome, descricao, preco_venda, rendimento)
                    VALUES (?, ?, ?, ?)
                """, (
                    nome,
                    descricao,
                    preco_venda,
                    rendimento
                ))

                produto_id = cursor.lastrowid

                for ingrediente_id, quantidade in itens_receita:
                    conexao.execute("""
                        INSERT INTO receita_itens
                        (produto_id, ingrediente_id, quantidade)
                        VALUES (?, ?, ?)
                    """, (
                        produto_id,
                        ingrediente_id,
                        quantidade
                    ))

            return redirect(url_for("produtos"))

        except ValueError as erro:
            mensagem = str(erro)

        except sqlite3.Error as erro:
            print("ERRO AO CADASTRAR PRODUTO:", repr(erro))
            mensagem = (
                "Não foi possível salvar o produto. "
                "Confira os dados e tente novamente."
            )

    with conectar_banco() as conexao:
        lista_produtos = conexao.execute(
            "SELECT * FROM produtos ORDER BY nome"
        ).fetchall()

        produtos_com_receitas = []

        for produto in lista_produtos:
            itens = conexao.execute("""
                SELECT receita_itens.quantidade,
                       ingredientes.nome AS ingrediente_nome,
                       ingredientes.unidade AS ingrediente_unidade
                FROM receita_itens
                JOIN ingredientes
                    ON ingredientes.id = receita_itens.ingrediente_id
                WHERE receita_itens.produto_id = ?
                ORDER BY ingredientes.nome
            """, (produto["id"],)).fetchall()

            produtos_com_receitas.append({
                "id": produto["id"],
                "nome": produto["nome"],
                "descricao": produto["descricao"],
                "preco_venda": produto["preco_venda"],
                "rendimento": produto["rendimento"],
                "receita": itens
            })

    return render_template(
        "produtos.html",
        ingredientes=lista_ingredientes,
        produtos=produtos_com_receitas,
        mensagem=mensagem
    )


criar_tabelas()


if __name__ == "__main__":
    app.run(debug=True)
