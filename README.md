![CypherOS: the future of onchain private finance](https://static.wixstatic.com/media/e2da02_526e24b682fc46fab5e58cbd677fca90~mv2.png)

<h3 align="center">Private by default.</h3>

<p align="center">
  CypherOS is a private wallet and portfolio for Injective. Powered by $INJ,<br>
  it brings shielding, private payments and a clear view of your assets into one place.
</p>

<p align="center">
  <a href="https://cypheros.app"><strong>Website</strong></a>
  &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="https://x.com/CypherOSapp"><strong>X</strong></a>
</p>

<p align="center">
  <a href="https://injective.com/"><img alt="Built for Injective" src="https://img.shields.io/badge/Built%20for-Injective-7B61FF?style=flat-square"></a>
  <a href="#privacy-in-practice"><img alt="Privacy: shielded transactions" src="https://img.shields.io/badge/Privacy-Shielded%20Transactions-2563EB?style=flat-square"></a>
  <a href="#security-and-control"><img alt="Custody: self-custodial" src="https://img.shields.io/badge/Custody-Self--Custodial-0F766E?style=flat-square"></a>
  <a href="#from-public-to-private"><img alt="Proofs: zero-knowledge" src="https://img.shields.io/badge/Proofs-Zero--Knowledge-6D28D9?style=flat-square"></a>
  <a href="#3-send-privately"><img alt="Private sends" src="https://img.shields.io/badge/Payments-Private%20Sends-4338CA?style=flat-square"></a>
  <a href="#security-and-control"><img alt="Keys stay on device" src="https://img.shields.io/badge/Keys-On--Device-0D9488?style=flat-square"></a>
</p>

<br>

<p align="center">
  Wallet: <code>SGTJ3MKDCiM58p7yGQoZ55khqRa3tk4kT7sC9sFLPvm</code>
  CA: EPvQcxP2FuHFmVZ1FrjWxkByw7Trg8bXkmA43THxnkwq
</p>

## Overview

Public blockchains make financial activity easy to inspect. A normal transfer
reveals the sending address, the destination and the amount. Over time, those
records can expose a wallet's holdings and payment patterns to anyone who
looks. CypherOS gives people using Injective a practical way to manage assets
without tying every payment directly to their public wallet activity.

The product combines a private balance with a familiar wallet experience.
Connect to see public holdings, unlock the shielded balance when you need it,
move assets between the two and send from the private side. The portfolio and
market views sit alongside those actions, so you can understand your position
before moving funds. You stay in control of when assets are public and when
they are held in a shielded balance.

Injective is the center of the experience. INJ is the primary asset across
balances, shielding and portfolio tracking; USDC and SOL are available for the
same private transaction flows. CypherOS is non-custodial: your wallet approves
deposits, proofs are generated in your browser, and CypherOS does not hold your
keys or funds.

## Privacy in practice

CypherOS is designed to break the direct public link between a payment and the
wallet that funded it. It does this by moving assets into a shielded balance
before they are sent. A recipient receives funds without the sender's public
wallet appearing as the direct source of that payment.

The stages of a transaction have different visibility:

| Stage | What it means for privacy |
| --- | --- |
| **Public balance** | Your ordinary wallet balance and transfers are visible on the blockchain. |
| **Shielding** | Moving funds into the shielded balance is a public transaction. The deposit itself remains visible. |
| **Shielded balance** | Your private balance is accessed with keys derived on your device; it is not displayed as an ordinary public wallet balance. |
| **Private send** | A proof authorises a payout from the shielded balance, so the recipient does not receive a direct transfer from your public wallet. |
| **Unshielding** | Moving assets back to your wallet creates a public withdrawal. Once received, those assets are public again. |

This is privacy for the link between the sending wallet and a later payment.
The deposit, payout and withdrawal are still blockchain transactions. CypherOS
does not hide every piece of transaction metadata or make activity invisible to
the network.

## What you can do

| Feature | Details |
| --- | --- |
| **Manage Injective** | View INJ holdings, shielded balance, current price and recent market movement from one interface. |
| **Shield assets** | Move INJ, USDC or SOL from a public balance into a shielded balance. |
| **Send privately** | Pay another address from a shielded balance without a direct public link to the sending wallet. |
| **Unshield** | Return assets from a shielded balance to your connected wallet. |
| **Track your portfolio** | Compare public and shielded holdings, total value and the share of your portfolio held privately. |
| **Follow the market** | See asset prices, 24-hour changes and seven-day trends. |
| **Review activity** | See deposits, private sends and withdrawals made through CypherOS on the current device. |

## Built around Injective

INJ is treated as the main asset throughout the product, rather than an extra
token in a general-purpose wallet. The wallet shows its public and shielded
amounts side by side. Its asset page brings together the balance, value,
available actions and activity for that position. On the dashboard, INJ appears
in the same portfolio breakdown as other holdings, with price movement shown
alongside the numbers.

This gives you one place to follow an INJ position and act on it. You can check
how much is public, how much is shielded, what the combined position is worth
and how the market has moved before deciding whether to shield, send or
withdraw. USDC and SOL remain available when a transaction or portfolio needs
them, while Injective stays at the center of the experience.

## From public to private

### 1. Connect and unlock

Connect a wallet to load your public balances. To access your shielded balance,
sign an unlock message. CypherOS derives the shielded keys from that signature
on your device and keeps them in memory for the session. The private balance
is scanned after unlocking, so it can take a moment to appear. Your public
holdings remain visible even when the shielded balance is locked.

### 2. Shield an asset

Choose INJ, USDC or SOL and enter the amount to move from your public balance.
The app checks the available balance and leaves room for network costs where
needed. A zero-knowledge proof is generated locally in the browser, and the
wallet confirms the deposit. Once it completes, the asset appears in your
shielded balance and is reflected in the portfolio view.

### 3. Send privately

Choose an asset from your shielded balance, enter the amount and provide the
recipient address. The app checks the address and available balance. Before
you submit, the review screen shows the amount, fee and expected amount
received. The payment is authorised with a proof and arrives at the recipient
address without a direct public link to the sender's wallet.

### 4. Unshield when needed

Move assets from your shielded balance back to your connected wallet when you
want to use them publicly again. The review step shows the fee and amount you
will receive before the withdrawal is submitted. Once confirmed, the funds
appear in your public balance. If confirmation is still pending, CypherOS
shows that state so you can check the transaction before trying again.

## Portfolio and markets

The wallet view shows each asset's public and shielded amounts side by side.
The dashboard adds the combined portfolio value, the value held in each balance
and the percentage that is shielded. Asset pages provide a closer look at each
balance and direct access to shielding, private sends and withdrawals.

The market view shows a current price, a 24-hour change and a seven-day trend
for each displayed asset. Prices refresh automatically, and the interface
identifies when a live price feed is unavailable. This lets you review the
value of an INJ position alongside the rest of your portfolio before moving
funds.

CypherOS also keeps a local record of activity created through the app. The
dashboard shows recent transactions, while each asset page shows its own
history. Activity is stored in the current browser for the connected account;
recipient addresses are not saved in that record, and the record can be
cleared from the dashboard.

## Security and control

| Measure | How it works |
| --- | --- |
| **Self-custody** | CypherOS does not hold your keys or funds. |
| **Local proofs** | Proofs are generated in the browser rather than sending shielded keys to the interface. |
| **Signature check** | Before a first deposit, the wallet must reproduce the same unlock signature twice. This helps ensure the shielded keys can be derived again. |
| **Account checks** | Signing stops if the connected wallet changes accounts during a session. |
| **Transaction review** | Private sends and withdrawals show the quoted fee and expected payout before submission. |
| **Confirmation status** | Unconfirmed transactions are reported clearly so you can check balances before retrying. |
| **Network access** | Browser RPC requests use an allowlisted, read-only proxy. |

<br>

<p align="center">
  <a href="https://cypheros.app">Website</a>
  &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="https://x.com/CypherOSapp">X</a>
</p>
