# GLUA Retro Arcade — guia do evento

## Voluntários

Entra no endereço local indicado pelo Mac, usa o teu nome e o PIN de voluntário. Só há três provas oficiais. As estações 4 e 5 são sempre jogo livre. Todos os Pis têm a mesma biblioteca, mas as provas oficiais só decorrem nas mesas físicas 1, 2 e 3, devidamente identificadas.

Procura e seleciona a alcunha; só regista uma nova se ainda não existir. Confirma em voz alta o jogador, a prova e as tentativas disponíveis. Nunca registes uma tentativa por abrir um jogo.

- Plataformas/combate: prepara o jogo → **Iniciar** no sinal definido abaixo → **Parar** no fim → confirma o valor → **Guardar**.
- Corridas: prepara o Time Trial → acompanha a corrida → lê o tempo total das cinco voltas → introduz `MM:SS.CC` → **Guardar**.
- Morte, derrota, abandono ou infração: **Tentativa falhada**. Também conta para o limite de três.
- A classificação usa o melhor tempo válido; menor é melhor. Empates: inscrição mais antiga primeiro. Não há classificação geral combinada.
- Erro de transcrição, jogador errado ou avaria: chama um admin. Ele corrige/anula com motivo; não tentes compensar com um resultado falso.

Depois de perder ligação, espera e verifica o histórico. Uma tentativa parada ocupa a estação até confirmação. Se a aplicação reiniciar durante a medição, a tentativa fica falhada por segurança; um admin decide se a anula por avaria. Não reinicies a aplicação para resolver um simples problema do telemóvel.

## Condições comuns

Usar a mesma ROM USA/NTSC, mesmo core, comando e configurações durante a prova inteira. Não misturar PAL e NTSC. Antes de abrir inscrições, copiar os SHA-256 de `build/readiness.json` para a ficha abaixo e confirmar os jogos no hardware. Se mudar ROM/core ou regras após a abertura, não misturar resultados: suspender a prova e resolver com a organização.

Sem cheats, rewind, turbo, fast-forward, pausa durante a tentativa ou save states. As configurações desativam rewind/autosave; os voluntários devem vigiar os restantes atalhos. As ROMs podem ser usadas em jogo livre fora das tentativas; repor o estado de partida antes da prova seguinte. Usa o menu RetroArch **Restart/Reset** ou sai e relança; não uses sequências de teclas automatizadas.

Save states ficam **desativados para o torneio**: não há ROM/core/hardware disponíveis para verificar a igualdade do estado e do comportamento. Só considerar uma futura revisão das regras depois de criar e testar o mesmo estado, hash, core/versão e condições para todos; nunca mudar a meio do evento.

## 1 · Super Mario World — Yoshi’s Island 1

SNES USA, novo jogo, ficheiro limpo sem progresso; Mario pequeno, sem Yoshi, sem item de reserva. Selecionar Yoshi’s Island 1. O voluntário deixa o nível pronto, sem movimento. **Iniciar** quando autoriza o primeiro movimento do jogador; **Parar** ao primeiro contacto com a fita da meta. Não esperar pela contagem de pontos. Completar normalmente, sem glitches/saídas alternativas. Morrer ou abandonar = falha; refazer novo jogo antes de outra tentativa. Três tentativas.

## 2 · Street Fighter II — derrotar a CPU

Edição **SNES Street Fighter II: The World Warrior (USA)**, não Turbo nem Super. Personagem **Ryu**, adversário **Dhalsim CPU**, dificuldade **1 estrela**, velocidade **original** (esta edição não tem seletor Turbo), tempo do jogo normal, combate melhor de três rounds (primeiro a ganhar dois).

Reiniciar o jogo, fixar opções e selecionar Ryu. **Confirmar que o primeiro adversário é Dhalsim**. Se aparecer outro, reiniciar e repetir a preparação antes de criar a tentativa oficial; a ordem da CPU não é assumida como determinística. Nunca contar esse trabalho de preparação como tentativa do participante. Não usar um segundo jogador humano como CPU. Se não for possível reproduzir este confronto na ROM disponível, a prova fica pendente até validação presencial; não improvisar adversários diferentes.

**Iniciar** no `FIGHT` do primeiro round; **Parar** no `KO` do round que dá a segunda vitória a Ryu. O cronómetro continua entre rounds; ganhar por timeout é permitido e inclui o tempo até aparecer a indicação de vitória do round decisivo. Double KO: seguir a decisão do jogo; o combate só termina quando Ryu ganha dois rounds. Perder o combate ou abandonar = falha, sem continues. Reiniciar e preparar o mesmo confronto para a tentativa seguinte. Três tentativas.

## 3 · Super Mario Kart — Mario Circuit 1

SNES USA, **Time Trial**, personagem **Mario**, **Mushroom Cup → Mario Circuit 1**. O Time Trial tem classe/velocidade própria e não oferece seleção de cilindrada; não usar Grand Prix nem inventar uma configuração “150 cc”. Preparar uma corrida nova desde a linha de partida; completar **cinco voltas**. Registar o **tempo total mostrado pelo jogo**, nunca uma volta isolada nem o cronómetro da aplicação. Sem itens externos, atalhos com glitches ou ghost obtido de outra pessoa; usar condições iguais para todos. Abandono ou infração = falha. Três tentativas.

## Ficha antes da abertura

Preencher após validação presencial (ainda não realizada):

| Prova | SHA-256 da ROM | Core/versão | Configuração e reposição confirmadas por |
|---|---|---|---|
| Super Mario World | | | |
| Street Fighter II — Ryu / Dhalsim | | | |
| Super Mario Kart | | | |

Testar uma tentativa completa de cada prova, confirmar o retorno **Hotkey + Start**, testar inscrições/limites com a base demo e só depois iniciar a base real vazia.
