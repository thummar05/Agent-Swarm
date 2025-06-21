# data/user_data.py

# User Database (Mock Data)
USER_DATABASE = {
    "client123": {
        "name": "João Silva",
        "email": "joao@email.com",
        "phone": "+55 11 99999-9999",
        "account_status": "active",
        "balance": 1250.50,
        "created_date": "2023-01-15",
        "transactions": [
            {"id": "tx001", "amount": -50.00, "date": "2025-06-15", "description": "Compra loja ABC"},
            {"id": "tx002", "amount": 200.00, "date": "2025-06-14", "description": "Depósito PIX"},
            {"id": "tx003", "amount": -25.30, "date": "2025-06-13", "description": "Pagamento cartão"}
        ]
    },
    "client456": {
        "name": "Maria Santos",
        "email": "maria@email.com",
        "phone": "+55 11 88888-8888",
        "account_status": "suspended",
        "balance": 0.00,
        "created_date": "2023-05-20",
        "transactions": [
            {"id": "tx004", "amount": -100.00, "date": "2025-06-10", "description": "Compra online"}
        ]
    },
    "client789": {
        "name": "Carlos Oliveira",
        "email": "carlos@email.com",
        "phone": "+55 11 77777-7777",
        "account_status": "active",
        "balance": 500.75,
        "created_date": "2023-03-25",
        "transactions": [
            {"id": "tx005", "amount": -300.00, "date": "2025-06-12", "description": "Pagamento boleto"},
            {"id": "tx006", "amount": 400.00, "date": "2025-06-11", "description": "Depósito via transferência"},
            {"id": "tx007", "amount": -50.00, "date": "2025-06-10", "description": "Compra online"}
        ]
    },
    "client101": {
        "name": "Luciana Almeida",
        "email": "luciana@email.com",
        "phone": "+55 11 66666-6666",
        "account_status": "active",
        "balance": 1500.00,
        "created_date": "2023-02-01",
        "transactions": [
            {"id": "tx008", "amount": 1000.00, "date": "2025-06-09", "description": "Depósito bancário"},
            {"id": "tx009", "amount": -200.00, "date": "2025-06-08", "description": "Compra loja XYZ"},
            {"id": "tx010", "amount": -300.00, "date": "2025-06-07", "description": "Pagamento fatura cartão"}
        ]
    },
    "client112": {
        "name": "Felipe Costa",
        "email": "felipe@email.com",
        "phone": "+55 11 55555-5555",
        "account_status": "active",
        "balance": 2200.40,
        "created_date": "2022-12-05",
        "transactions": [
            {"id": "tx011", "amount": -150.00, "date": "2025-06-14", "description": "Compra supermercado"},
            {"id": "tx012", "amount": 500.00, "date": "2025-06-13", "description": "Depósito de salário"},
            {"id": "tx013", "amount": -200.00, "date": "2025-06-12", "description": "Compra gasolina"}
        ]
    },
    "client131": {
        "name": "Ana Pereira",
        "email": "ana@email.com",
        "phone": "+55 11 44444-4444",
        "account_status": "active",
        "balance": 750.30,
        "created_date": "2023-04-18",
        "transactions": [
            {"id": "tx014", "amount": -120.50, "date": "2025-06-14", "description": "Compra online"},
            {"id": "tx015", "amount": 250.00, "date": "2025-06-13", "description": "Transferência recebida"},
            {"id": "tx016", "amount": -50.00, "date": "2025-06-12", "description": "Compra em loja física"}
        ]
    },
    "client141": {
        "name": "Rafael Martins",
        "email": "rafael@email.com",
        "phone": "+55 11 33333-3333",
        "account_status": "inactive",
        "balance": 80.00,
        "created_date": "2023-06-10",
        "transactions": [
            {"id": "tx017", "amount": -30.00, "date": "2025-06-15", "description": "Pagamento de conta"},
            {"id": "tx017", "amount": -30.00, "date": "2025-06-15", "description": "Pagamento de conta"},
            {"id": "tx018", "amount": 50.00, "date": "2025-06-14", "description": "Depósito"},
            {"id": "tx018", "amount": 50.00, "date": "2025-06-14", "description": "Depósito"},
            {"id": "tx018", "amount": 50.00, "date": "2025-06-14", "description": "Depósito"},
            {"id": "tx016", "amount": -50.00, "date": "2025-06-12", "description": "Compra em loja física"}
        ]
    }
}
