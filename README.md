# GLUA Retro Arcade

Todos os Raspberry Pis são **Pi 3 Model B+** e recebem **a mesma imagem, biblioteca e configurações**. Cada cartão guarda os seus saves. Os jogos funcionam sem rede; dois Pis podem correr o mesmo jogo ao mesmo tempo. A aplicação do torneio é independente e mantém três provas, três tentativas por participante/prova, tema escuro e administração.

## Preparar os cartões: tudo no Mac

```sh
cd ~/Documents/GLUA/retro_pi_gameroom
./prepare.sh              # criar/atualizar o master uma vez por alteração
./flash.sh --dry-run      # ensaiar sem escrever cartões
./flash.sh                # repetir este comando para cada cartão
```

1. Coloca as ROMs e BIOS legais nas pastas abaixo e executa `./prepare.sh`.
2. Marca os jogos pretendidos com `selected: true` em `config/games.json` e volta a preparar. Consulta `build/LIBRARY.md` (disponíveis/selecionados/em falta) e `build/READINESS.txt` (imagem, capacidade mínima e espaço para saves). O detalhe está em `build/readiness.json` e `build/master-readiness.json`.
3. Liga um cartão ao leitor do Mac e executa `./flash.sh`. Escolhe explicitamente o identificador do cartão, verifica nome/capacidade e escreve a confirmação de apagamento. O script pede `sudo`, grava, compara todos os bytes e ejeta. **Apaga todo o cartão escolhido. Recusa discos internos.**
4. Insere o cartão em qualquer Pi 3B+, liga o ecrã e os dois comandos e dá alimentação. Não é necessário SSH, Wi-Fi, Ethernet, deployment ou cópia de ficheiros no Pi.

A preparação usa Python, `e2fsprogs` e `mtools` nativos, e o `7z` para inspecionar o sistema. Instala apenas ferramentas em falta por Homebrew, sem atualizar o sistema inteiro nem editar a shell. Não usa VM, Docker ou um driver ext4. Precisa de Internet para o primeiro download/instalação de dependências; os ficheiros ficam em cache e podem ser reutilizados offline. A aplicação Python usa uma `.venv` própria. Para preparar apenas a aplicação: `./prepare.sh --app-only`.

O master fica em `cache/master/glua-arcade-pi3bplus.img`. **Não é reconstruído nem descarregado por cartão.** Volta a executar `./prepare.sh` se acrescentares jogos, BIOS ou mapeamentos; os cartões já gravados mantêm o conteúdo anterior. Regravar apaga também os saves desse cartão.

A imagem compacta atual ocupa aproximadamente **7,59 GB**, sem ROMs: boot de 6 GiB e userdata de cerca de 1,14 GB, com aproximadamente 1 GiB livre. O relatório dá os valores exatos. O tamanho aumenta com os jogos e só entram cartões com capacidade real suficiente; não se confia apenas na etiqueta “8 GB”.

Escolhe um dos modos por cartão:

| Comando | Armazenamento |
|---|---|
| `./flash.sh` | Grava o master compacto, rapidamente; espaço adicional do cartão fica por utilizar. |
| `./flash.sh --fill-card` | Cria uma cópia temporária no Mac, expande o ext4 para a capacidade real e verifica-a antes de pedir a confirmação de apagamento. Fica menos de 1 MiB fora das partições. |

O modo `--fill-card` **não altera o master** nem os jogos selecionados: cresce uma cópia com `resize2fs`, ajusta a segunda partição e confirma filesystem/ficheiros/arranque antes de gravar. A confirmação continua obrigatória, o disco é novamente identificado imediatamente antes da escrita e todos os bytes são comparados depois. Os saves existentes no cartão são apagados por qualquer regravação; não é uma expansão de um cartão em uso.

A expansão é mais lenta e precisa de espaço temporário no Mac: a verificação exige uma margem conservadora de cerca de **três vezes a capacidade do cartão, mais o tamanho dos ficheiros incluídos e 1 GiB**. Se não houver espaço, o script recusa antes de escrever no cartão; usa o modo compacto. Não é necessário instalar mais ferramentas. Limite MBR de aproximadamente 2 TiB; não se faz redução de filesystem para caber num cartão pequeno.

Para ver o plano sem gravar: `./flash.sh --dry-run --fill-card --disk diskN` (substitui pelo identificador do teu cartão listado). Mostra capacidade, tamanho a gravar, userdata e espaço não utilizado; o espaço livre exato é confirmado depois de construir a cópia. O ext4 pode deixar uma pequena margem dentro da partição quando o último grupo não comporta os seus metadados; esse valor é também reportado, sem reformatar ou perder ficheiros. Para aumentar apenas a margem do master compacto, edita `userdata_free_mib` em `config/master.json` e prepara novamente.

**Nos dois modos, `autoresize=false` mantém-se no Batocera.** Nenhuma expansão/formatação é deixada para o primeiro arranque do Pi. Os testes de expansão foram feitos em ficheiros no Mac; a primeira gravação e o arranque real ainda exigem a checklist final.

## Jogos, BIOS e biblioteca comum

Não são fornecidas nem descarregadas ROMs comerciais ou BIOS. Copia os teus ficheiros obtidos legalmente para:

```text
roms/nes/       roms/snes/       roms/megadrive/
roms/gb/        roms/psx/        roms/arcade/
bios/
```

`config/games.json` mantém os 32 pedidos originais e seis candidatos multiplayer. **Só entram os jogos com `selected: true`.** Super Mario World, Street Fighter II e Super Mario Kart estão selecionados por defeito; todos os outros começam com `false`. Não se descarregam ROMs ou BIOS.

Para acrescentar um jogo existente na lista, muda apenas `selected` para `true`. Para outro jogo, acrescenta uma entrada semelhante:

```json
{
  "title": "O meu jogo legal",
  "system": "snes",
  "aliases": ["O meu jogo legal"],
  "files": [],
  "selected": true,
  "optional": true
}
```

`aliases` reconhece nomes com regiões/revisões entre parênteses. Se houver várias versões diferentes de um jogo selecionado, escolhe uma explicitamente: `"files": ["Super Mario World (USA).sfc"]`, relativa à pasta do sistema. Essa lista tem prioridade sobre os aliases. Mantém a edição USA prevista nas regras para as provas.

O inventário `build/LIBRARY.md` mostra o catálogo, ficheiros encontrados, seleção e jogos em falta; `build/readiness.json` contém o detalhe, incluindo `available`, `selected`, `selected_missing`, bloqueios e erros. “Disponível” significa ficheiro encontrado, não desempenho validado. Um jogo selecionado sem ROM é reportado, sem criar uma entrada falsa no Pi.

Por defeito, `config/library.json` contém `"include_unlisted": false`: ficheiros extra **não entram**. Se escolheres explicitamente `true`, também entram jogos que não correspondam ao manifesto. Jogos explicitamente desmarcados continuam excluídos. Todos os Pis recebem a mesma seleção.

Pastas antigas `roms/stations/N/SISTEMA/` são lidas como fontes comuns, sujeitas à mesma seleção; usa as pastas globais para novas importações. Duplicados de conteúdo são identificados. Um mesmo nome com conteúdo diferente bloqueia a construção, sem substituir o original.

NES/SNES/Mega Drive/GB aceitam os formatos de `config/systems.json`, incluindo ZIP/7z. ZIP é verificado internamente; 7z é reconhecido por extensão. PS1: usa CHD, PBP, CUE com todos os BIN referenciados, ou M3U com os discos. Mantém subpastas e referências; BIN não aparece sozinho como jogo. As listas de jogos são geradas apenas para ficheiros existentes e incluem os três jogos oficiais nos favoritos.

BIOS: copia os dumps para `bios/`. O relatório compara `scph5500.bin`, `scph5501.bin` e `scph5502.bin` com os hashes da Libretro; pelo menos uma BIOS reconhecida é necessária para preparar jogos PS1 sem erro. Outros BIOS fornecidos também são copiados. Nada é descarregado pelo Pi.

Arcade requer um romset compatível com **FBNeo**, não um ZIP arbitrário. A pasta de entrada é `roms/arcade/`, o destino Batocera é `roms/fbneo/`. Só os nomes declarados em `validated_files` de `config/arcade.json` são incluídos; indica-os depois de verificar o romset e as dependências, incluindo BIOS/parent ROMs quando necessários. Os restantes ficam no relatório como bloqueados. Não há garantia de desempenho físico de Puzzle Bobble ou de outro arcade.

PS1 usa PCSX ReARMed, resolução nativa, sem enhanced resolution, rewind, runahead ou shaders. Testa os seis títulos no Pi 3B+, sobretudo Tekken 3 e os jogos de corrida. Para retirar um título problemático de todos os cartões, muda `selected` para `false` e volta a preparar o master. Não há configurações diferentes por placa.

## Dois comandos: primeiro arranque e reutilização

1. **Liga dois comandos por USB e testa primeiro.** A imagem 43.1 contém 303 perfis de joystick, incluindo famílias Xbox, Sony, 8BitDo e Logitech. Muitos modelos já são reconhecidos; o GUID, firmware e modo de ligação podem mudar o resultado. Não foram testados os teus comandos.
2. Abre um jogo de dois jogadores, por exemplo Super Mario Kart em VS/Battle, e confirma que cada comando controla um jogador diferente. Se houver troca, ajusta a atribuição dos jogadores em **Controller & Bluetooth Settings**. Usa as mesmas portas USB nos outros Pis.
3. **Só se os botões estiverem errados**, usa **Controller Mapping** e segue o assistente. Mapeia o primeiro, testa o segundo e mapeia-o também se necessário. Inclui direções, seis botões, Start/Select e Hotkey. **Hotkey + Start** regressa ao menu. Comandos com o mesmo GUID podem partilhar o mapa; confirma os dois jogadores no jogo.

Se os perfis de origem funcionarem, **não é preciso importar nada**: os outros cartões já têm os mesmos perfis. Bluetooth pode exigir emparelhamento local em cada Pi; o importador não copia chaves de emparelhamento. USB é o caminho mais simples para a primeira preparação.

Para reutilizar um **mapeamento manual já testado**, sem rede:

1. Desliga o primeiro Pi pelo menu e coloca esse cartão no Mac.
2. Executa `python3 scripts/import-controllers.py`, escolhe o cartão e confirma `TESTEI DOIS COMANDOS`. A ferramenta só lê o cartão; pede `sudo` e guarda o mapa localmente.
3. Executa `./prepare.sh` uma vez e grava os outros cartões normalmente.

A configuração fica em `config/controllers.json` e o mapa em `controllers/es_input.cfg`. Só um mapa declarado validado com dois jogadores entra no master; a ferramenta verifica a estrutura, não o comportamento físico. **Ainda não existem mapeamentos físicos validados neste projeto.**

Candidatos simultâneos: Street Fighter II, Mortal Kombat II, TMNT Tournament Fighters, Super Mario Kart (VS/Battle), Micro Machines 2, TMNT IV/Hyperstone Heist, Streets of Rage 2, Contra III, Super Bomberman 2 e NBA Jam TE. Cada edição precisa de teste; jogos como Super Mario World têm modo alternado, não cooperativo simultâneo. As provas oficiais continuam a ser individuais.

## Aplicação e torneio

```sh
./run-app.sh
```

No Mac: `http://localhost:8080`. O script mostra o IPv4 que os voluntários abrem nos telemóveis. **Só o Mac e os telemóveis precisam de estar na mesma rede local**; os Pis podem ficar totalmente desligados da rede. Não é necessária Internet. Permite o servidor na firewall se o macOS pedir. Mantém o Mac ligado à corrente e com tampa aberta; `caffeinate` evita suspensão por inatividade. Após reiniciar o Mac, volta a executar o script. Usa apenas uma instância por base de dados.

A conta administrativa existente e a palavra-passe foram preservadas. `.local.json` guarda `admin_username`, `admin_hash` e o PIN dos voluntários; está ignorado pelo Git e com permissões 600. Alternativas por ambiente: `GLUA_ADMIN_PIN`, `GLUA_VOLUNTEER_PIN`, `GLUA_SECRET`. Usa uma rede de confiança; o serviço HTTP não cifra as credenciais. Não expor a porta na Internet.

Em **Administração → Gerir contas dos voluntários**, cria uma conta para cada colaborador com utilizador, nome e palavra-passe inicial (8–128 caracteres). Partilha as credenciais diretamente; só o hash da palavra-passe é guardado. Estas contas podem registar participantes e tentativas, mas não administrar a aplicação.

Para retirar acesso, usa **Apagar conta**, indica o motivo e escreve `APAGAR utilizador`. As sessões dessa conta perdem acesso no próximo pedido. Participantes, tentativas, cronómetros e resultados são preservados; outro voluntário ou o admin pode concluir um cronómetro em curso. As ações ficam na auditoria. A reposição dos dados do torneio não apaga as contas.

Ao criar uma conta, a opção recomendada é **desativar o PIN partilhado**, terminando também os acessos antigos por PIN. Podes gerir essa opção na mesma página. Enquanto o PIN estiver ativo, quem o souber pode entrar sem conta individual, mesmo que uma conta tenha sido apagada. A conta admin mantém-se independente e não pode ser apagada nessa página.

1. Entra com a tua conta individual (ou PIN, se estiver ativo) e escolhe a prova.
2. Procura a alcunha antes de registar outra; pessoas diferentes devem usar alcunhas distintas.
3. Plataformas/combate: **Iniciar → Parar → Confirmar e guardar**. Corridas: tempo do jogo em `MM:SS.CC` → guardar.
4. Falhas/abandonos contam; cada pessoa tem três tentativas por prova. Cronómetros parados ocupam a estação até confirmação. Refresh recupera o estado; reiniciar o servidor com um cronómetro a decorrer marca-o como falhado, com auditoria.

**Estações físicas 1/2/3** mantêm as provas Super Mario World/Street Fighter II/Super Mario Kart. **4/5 são jogo livre**, apesar de todas terem os mesmos jogos. Etiqueta as placas/mesas fisicamente. `config/stations.json` serve de inventário e associação às provas, sem modelo ou endereço de rede; podes desativar/remover estações de jogo livre se só houver quatro placas. Não altera regras nem dados da aplicação. Regras completas em [EVENT.md](EVENT.md).

Administração: corrigir/anular tentativas com motivo; apagar participante escrevendo `APAGAR ID`; repor dados escrevendo `APAGAR TODOS OS DADOS`. A eliminação fica auditada e bloqueia enquanto houver tentativa por concluir. A reposição apaga também resultados reais se a confirmares; mantém contas, definições e auditoria. Nada é apagado automaticamente. CSV de participantes/tentativas/classificações/auditoria; tempos em centésimos, desempate por inscrição mais antiga.

## Cópias e verificação

A base real permanece em `data/tournament.sqlite3`. Backups online a cada cinco minutos e após alterações em `data/backups/`; cópia extra: `.venv/bin/python scripts/backup.py`. Exporta CSV e guarda uma cópia externa no fim. Para restaurar, para o servidor e usa uma cópia do backup numa pasta nova: `GLUA_DATABASE=/caminho/restauro.sqlite3 ./run-app.sh`. Não substituas uma base aberta.

```sh
.venv/bin/python -m unittest discover -s tests -v
python3 scripts/master.py --verify-only    # verifica o master sem reconstruir
./prepare.sh --dry-run
./flash.sh --dry-run
```

Demo isolada: `.venv/bin/python scripts/demo.py`, depois `GLUA_DATABASE=data/demo.sqlite3 ./run-app.sh` com o servidor real parado. Nunca mistura resultados com a competição.

**Primeiro arranque físico:** confirmar menu Carbon, lista comum de jogos, vídeo/áudio, comandos 1/2 em menus e jogos simultâneos, saída Hotkey+Start, saves locais após desligar/religar e desempenho/temperatura PS1. Testar a preparação repetível das três provas e seguir EVENT.md antes de abrir inscrições. Ainda não foram ensaiados arranque, gravação física, comandos ou desempenho em hardware. Detalhes técnicos e fontes: [RESEARCH.md](RESEARCH.md).
