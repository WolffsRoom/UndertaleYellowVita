# Notas do port

## Layout no Vita

```text
ux0:data/undertale-yellow/
  data.win
  options.ini
  mus/
  snd/
  save/
  butterscotch.log
```

## Convencao de controles inicial

- Direcional/analogico esquerdo: movimento
- Cross: confirmar (`Z`)
- Circle ou Square: cancelar (`X`)
- Triangle: acao secundaria (`C`)
- Start: Enter
- Select: abre/fecha o Game Settings

## Diagnostico

O runner grava o progresso de carga e falhas iniciais em
`ux0:data/undertale-yellow/butterscotch.log`. O primeiro objetivo de hardware e
obter `BOOT=first_room_ready`; depois disso, erros de builtin e renderizacao
devem ser tratados individualmente.

## Rebuild e cache experimental

O Rebuild encontrou 287 Rooms, 83 Texture Pages originais e 18.737 TPIs. A
saida validada possui 1.584 Texture Pages e SHA-256
`7C169B496158B96D5606E7947239BEE772638918C85828F830495B88A85E6E18`.
O cache correspondente contem 1.584 arquivos R444 e 1.584 BC3. Como o arquivo
reconstruido cresceu de cerca de 152 MiB para 392 MiB, ele deve ser tratado
como experimental ate completar testes visuais e de carregamento no Vita.
