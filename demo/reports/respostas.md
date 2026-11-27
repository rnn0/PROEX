# Respostas às perguntas do projeto

## Pergunta 1 — Dá para saber pela chuva, antes da colheita, quais municípios vão perder a safra?

Com a chuva acumulada até o fim de **jan**, o modelo já alcança
96% do melhor desempenho possível (ROC-AUC 0.64,
PR-AUC 0.74; taxa base de acionamento 65%).
A previsão sai durante a estação de chuvas, antes do fim da colheita. O pagamento do benefício só começa,
em mediana, **13 meses** depois do fim de jan: essa é a folga
para a gestão pública se preparar. A antecedência é em relação ao pagamento, não à perda.

Escopo: Semiárido (área da Sudene) e as lavouras de sequeiro cobertas pelo programa (feijão, milho, arroz,
mandioca e algodão), com uma safra por ano.

- ROC-AUC usando só chuva, por mês de corte: jan: 0.55, fev: 0.52, mar: 0.53, abr: 0.57, mai: 0.59, jun: 0.60
- Baseline "histórico do município": ROC-AUC 0.56
- Fatores mais importantes: Fração das safras anteriores em que o município recebeu o benefício; Dias com chuva >= 1 mm na estação; Maior veranico (dias secos seguidos) de jan até o corte; Latitude do município; Chuva da estação em % da média histórica do local

## Pergunta 2 — Em quais municípios a perda de safra se repete quase todo ano?

**1107 de 1317 municípios** (recebeu o benefício em >= 50% das safras)
concentram **96%** de todo o valor pago no período.
O K-Means isolou um segmento de **perda estrutural** com 31 municípios,
que acionaram o benefício em 74% das safras em média
(chuva normal de 682 mm na estação).
Para esses municípios, a perda não é exceção: é a regra — o que indica a necessidade de políticas
permanentes (cisternas e tecnologias de captação de água, sementes adaptadas, assistência técnica),
e não só do seguro emergencial.

UFs com mais municípios recorrentes: BA (251), PB (168), CE (143), PI (137), RN (135).
Municípios recorrentes com risco alto já previsto para a safra atual: 950.

| Município | UF | Safras com benefício |
|---|---|---|
| Girau do Ponciano | AL | 100% |
| Jussara | BA | 100% |
| Crateús | CE | 100% |
| Dom Basílio | BA | 100% |
| Ibimirim | PE | 100% |
| Central | BA | 100% |
| Betânia do Piauí | PI | 100% |
| Serra Preta | BA | 100% |
| Santa Rita de Cássia | BA | 100% |
| Cacimba de Dentro | PB | 100% |
| Oliveira dos Brejinhos | BA | 100% |
| Ibiassucê | BA | 100% |
| Macajuba | BA | 100% |
| Jatobá | PE | 100% |
| Iaçu | BA | 100% |
