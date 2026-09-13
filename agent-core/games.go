package main

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"strings"
	"sync"
)

// Game is a playable, stateful game the agent can host and play.
type Game interface {
	Name() string
	State() map[string]any
	// Move applies a human action and returns a message describing the outcome.
	Move(action string) (string, error)
	// Bot makes the agent play and returns a message.
	Bot() (string, error)
	// Auto makes the agent play autonomously for whoever's turn it is, so a
	// full match can be run with zero human interaction.
	Auto() (string, error)
	// Over reports whether the game has ended.
	Over() bool
}

// GameRegistry hosts in-memory game sessions keyed by a short id.
type GameRegistry struct {
	mu       sync.Mutex
	sessions map[string]Game
	next     int
}

func NewGameRegistry() *GameRegistry {
	return &GameRegistry{sessions: map[string]Game{}, next: 1}
}

func (g *GameRegistry) newID() string {
	id := fmt.Sprintf("g%d", g.next)
	g.next++
	return id
}

func (g *GameRegistry) New(kind string) (string, Game, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	var gm Game
	switch strings.ToLower(kind) {
	case "tic-tac-toe", "ttt":
		gm = newTTT()
	case "rps", "rock-paper-scissors":
		gm = newRPS()
	case "hangman":
		gm = newHangman()
	case "guess", "number-guess":
		gm = newGuess()
	case "blackjack", "bj":
		gm = newBlackjack()
	case "memory":
		gm = newMemory()
	case "idle-miner", "miner", "idle":
		gm = newMiner()
	default:
		return "", nil, fmt.Errorf("unknown game %q", kind)
	}
	id := g.newID()
	g.sessions[id] = gm
	return id, gm, nil
}

func (g *GameRegistry) Get(id string) (Game, bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	gm, ok := g.sessions[id]
	return gm, ok
}

func (g *GameRegistry) List() []string {
	return []string{"tic-tac-toe", "rps", "hangman", "number-guess", "blackjack", "memory", "idle-miner"}
}

// AutoPlay runs a full match of kind with zero human interaction: the agent
// plays both sides until the game is over, then returns a transcript.
func (g *GameRegistry) AutoPlay(kind string) (string, error) {
	id, gm, err := g.New(kind)
	if err != nil {
		return "", err
	}
	var b strings.Builder
	fmt.Fprintf(&b, "Autonomous %s (game %s):\n", gm.Name(), id)
	for i := 0; i < 200; i++ {
		if gm.Over() {
			fmt.Fprintf(&b, "over=true state=%s", mapStateJSON(gm.State()))
			return b.String(), nil
		}
		msg, err := gm.Auto()
		if err != nil {
			return "", fmt.Errorf("autoplay %s: %w", kind, err)
		}
		b.WriteString(msg)
		b.WriteString("\n")
	}
	fmt.Fprintf(&b, "max-move cap reached state=%s", mapStateJSON(gm.State()))
	return b.String(), nil
}

func mapStateJSON(s map[string]any) string {
	b, err := json.Marshal(s)
	if err != nil {
		return ""
	}
	return string(b)
}

// ---- Tic-Tac-Toe with a minimax bot ----

type ttt struct {
	board [9]string
	turn  string
	over  bool
}

func newTTT() *ttt { return &ttt{turn: "X"} }

func (t *ttt) Name() string { return "tic-tac-toe" }

func (t *ttt) Over() bool { return t.over }

func (t *ttt) winner() string {
	lines := [][]int{{0, 1, 2}, {3, 4, 5}, {6, 7, 8}, {0, 3, 6}, {1, 4, 7}, {2, 5, 8}, {0, 4, 8}, {2, 4, 6}}
	for _, l := range lines {
		a, b, c := t.board[l[0]], t.board[l[1]], t.board[l[2]]
		if a != "" && a == b && b == c {
			return a
		}
	}
	return ""
}

func (t *ttt) full() bool {
	for _, c := range t.board {
		if c == "" {
			return false
		}
	}
	return true
}

func (t *ttt) State() map[string]any {
	return map[string]any{
		"game":     t.Name(),
		"board":    t.board,
		"turn":     t.turn,
		"over":     t.over,
		"winner":   t.winner(),
		"controls": "cell: 0-8 (top-left to bottom-right)",
	}
}

func (t *ttt) Move(action string) (string, error) {
	if t.over {
		return "game over", nil
	}
	var cell int
	if _, err := fmt.Sscanf(action, "%d", &cell); err != nil || cell < 0 || cell > 8 {
		return "", fmt.Errorf("cell must be 0-8")
	}
	if t.board[cell] != "" {
		return "", fmt.Errorf("cell %d already taken", cell)
	}
	t.board[cell] = "X"
	if w := t.winner(); w != "" {
		t.over = true
		return fmt.Sprintf("You win! %s", renderBoard(t.board)), nil
	}
	if t.full() {
		t.over = true
		return "Draw. " + renderBoard(t.board), nil
	}
	t.turn = "O"
	msg, err := t.Bot()
	return msg, err
}

func renderBoard(b [9]string) string {
	var sb strings.Builder
	for i := 0; i < 9; i++ {
		c := b[i]
		if c == "" {
			c = "."
		}
		sb.WriteString(c)
		if i%3 == 2 {
			sb.WriteString("\n")
		} else {
			sb.WriteString(" ")
		}
	}
	return sb.String()
}

func (t *ttt) Bot() (string, error) {
	best, bestScore := -1, -2
	for i := 0; i < 9; i++ {
		if t.board[i] == "" {
			t.board[i] = "O"
			score := t.minimax(false)
			t.board[i] = ""
			if score > bestScore {
				bestScore = score
				best = i
			}
		}
	}
	if best < 0 {
		t.over = true
		return "Draw. " + renderBoard(t.board), nil
	}
	t.board[best] = "O"
	t.turn = "X"
	if w := t.winner(); w != "" {
		t.over = true
		return fmt.Sprintf("I win at %d! %s", best, renderBoard(t.board)), nil
	}
	if t.full() {
		t.over = true
		return "Draw. " + renderBoard(t.board), nil
	}
	return fmt.Sprintf("I played cell %d. %s", best, renderBoard(t.board)), nil
}

// botX plays the X side (the "human" side) using the same minimax search so
// the agent can play against itself with no human interaction. The shared
// minimax scores favor O (+1 O win), so X minimizes.
func (t *ttt) botX() (string, error) {
	best, bestScore := -1, 2
	for i := 0; i < 9; i++ {
		if t.board[i] == "" {
			t.board[i] = "X"
			score := t.minimax(true)
			t.board[i] = ""
			if score < bestScore {
				bestScore = score
				best = i
			}
		}
	}
	if best < 0 {
		t.over = true
		return "Draw. " + renderBoard(t.board), nil
	}
	t.board[best] = "X"
	t.turn = "O"
	if w := t.winner(); w != "" {
		t.over = true
		return fmt.Sprintf("X wins at %d! %s", best, renderBoard(t.board)), nil
	}
	if t.full() {
		t.over = true
		return "Draw. " + renderBoard(t.board), nil
	}
	return fmt.Sprintf("X played cell %d. %s", best, renderBoard(t.board)), nil
}

// Auto plays whichever side's turn it is, letting the agent run a full match
// by itself.
func (t *ttt) Auto() (string, error) {
	if t.turn == "X" {
		return t.botX()
	}
	return t.Bot()
}

func (t *ttt) minimax(me bool) int {
	if w := t.winner(); w != "" {
		if w == "O" {
			return 1
		}
		return -1
	}
	if t.full() {
		return 0
	}
	best := -2
	if me {
		best = -2
	} else {
		best = 2
	}
	for i := 0; i < 9; i++ {
		if t.board[i] == "" {
			if me {
				t.board[i] = "O"
				s := t.minimax(false)
				t.board[i] = ""
				if s > best {
					best = s
				}
			} else {
				t.board[i] = "X"
				s := t.minimax(true)
				t.board[i] = ""
				if s < best {
					best = s
				}
			}
		}
	}
	return best
}

// ---- Rock-Paper-Scissors ----

type rps struct {
	pScore, bScore int
	over           bool
}

func newRPS() *rps { return &rps{} }

func (g *rps) Name() string { return "rps" }
func (g *rps) Over() bool   { return g.over }
func (g *rps) State() map[string]any {
	return map[string]any{"game": g.Name(), "you": g.pScore, "me": g.bScore, "controls": "r, p, or s"}
}

func (g *rps) Move(action string) (string, error) {
	a := strings.ToLower(strings.TrimSpace(action))
	names := map[string]string{"r": "rock", "p": "paper", "s": "scissors"}
	p, ok := names[a]
	if !ok {
		return "", fmt.Errorf("choose r, p, or s")
	}
	bs := []string{"r", "p", "s"}[rand.Intn(3)]
	b := names[bs]
	msg := fmt.Sprintf("You chose %s, I chose %s. ", p, b)
	switch {
	case a == bs:
		msg += "Tie!"
	case (a == "r" && bs == "s") || (a == "p" && bs == "r") || (a == "s" && bs == "p"):
		g.pScore++
		msg += "You win this round."
	default:
		g.bScore++
		msg += "I win this round."
	}
	msg += fmt.Sprintf(" Score: you %d, me %d.", g.pScore, g.bScore)
	if g.pScore >= 3 || g.bScore >= 3 {
		g.over = true
		if g.pScore > g.bScore {
			msg += " Match over, you win!"
		} else {
			msg += " Match over, I win!"
		}
	}
	return msg, nil
}

func (g *rps) Bot() (string, error) {
	return g.Move([]string{"r", "p", "s"}[rand.Intn(3)])
}

func (g *rps) Auto() (string, error) {
	return g.Bot()
}

// ---- Hangman ----

var hangmanWords = []string{"android", "samsung", "jarvis", "robot", "pixel", "gadget", "neural", "linux", "camera", "battery"}

type hangman struct {
	word     string
	revealed string
	guessed  []string
	lives    int
	over     bool
	won      bool
}

func newHangman() *hangman {
	w := hangmanWords[rand.Intn(len(hangmanWords))]
	revealed := strings.Repeat("_ ", len(w))
	return &hangman{word: w, revealed: revealed, lives: 6}
}

func (g *hangman) Name() string { return "hangman" }
func (g *hangman) Over() bool   { return g.over }

func (g *hangman) State() map[string]any {
	return map[string]any{
		"game":     g.Name(),
		"word":     strings.TrimSpace(g.revealed),
		"guessed":  g.guessed,
		"lives":    g.lives,
		"over":     g.over,
		"won":      g.won,
		"controls": "a letter",
	}
}

func (g *hangman) Move(action string) (string, error) {
	letter := strings.ToLower(strings.TrimSpace(action))
	if len(letter) != 1 || letter < "a" || letter > "z" {
		return "", fmt.Errorf("send a single letter")
	}
	for _, gs := range g.guessed {
		if gs == letter {
			return "already guessed " + letter, nil
		}
	}
	g.guessed = append(g.guessed, letter)
	if strings.Contains(g.word, letter) {
		runes := []rune(g.word)
		out := make([]rune, len(runes)*2-1)
		for i, r := range runes {
			if i > 0 {
				out[i*2-1] = ' '
			}
			if containsRune(g.guessed, string(r)) {
				out[i*2] = r
			} else {
				out[i*2] = '_'
			}
		}
		g.revealed = string(out)
		if !strings.Contains(g.revealed, "_") {
			g.over = true
			g.won = true
			return "You got it! The word was " + g.word + ".", nil
		}
		return g.revealed, nil
	}
	g.lives--
	if g.lives <= 0 {
		g.over = true
		return fmt.Sprintf("Out of lives. The word was %s.", g.word), nil
	}
	return fmt.Sprintf("No %s. %d lives left. %s", letter, g.lives, g.revealed), nil
}

func (g *hangman) Bot() (string, error) {
	return g.Auto()
}

// Auto guesses the most common English letter not yet tried, so the agent can
// finish a hangman game entirely on its own.
func (g *hangman) Auto() (string, error) {
	const freq = "etaoinsrhdlucmfywgpbvkxqjz"
	for _, r := range freq {
		letter := string(r)
		if !containsRune(g.guessed, letter) {
			return g.Move(letter)
		}
	}
	return "no letters left to guess", nil
}

func containsRune(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// ---- Number guessing ----

type guess struct {
	target  int
	low     int
	high    int
	guesses int
	over    bool
	won     bool
}

func newGuess() *guess {
	return &guess{target: rand.Intn(100) + 1, low: 1, high: 100}
}

func (g *guess) Name() string { return "number-guess" }
func (g *guess) Over() bool   { return g.over }
func (g *guess) State() map[string]any {
	return map[string]any{"game": g.Name(), "range": []int{g.low, g.high}, "guesses": g.guesses, "over": g.over, "won": g.won, "controls": "a number 1-100"}
}

func (g *guess) Move(action string) (string, error) {
	var n int
	if _, err := fmt.Sscanf(action, "%d", &n); err != nil {
		return "", fmt.Errorf("send a number")
	}
	g.guesses++
	if n < 1 || n > 100 {
		return fmt.Sprintf("Guess between 1 and 100 (%d guesses so far).", g.guesses), nil
	}
	switch {
	case n == g.target:
		g.over = true
		g.won = true
		return fmt.Sprintf("Correct! It was %d in %d guesses.", g.target, g.guesses), nil
	case n < g.target:
		if n > g.low {
			g.low = n
		}
		return fmt.Sprintf("Higher! Range now %d-%d.", g.low, g.high), nil
	default:
		if n < g.high {
			g.high = n
		}
		return fmt.Sprintf("Lower! Range now %d-%d.", g.low, g.high), nil
	}
}

func (g *guess) Bot() (string, error) {
	n := (g.low + g.high) / 2
	return g.Move(fmt.Sprintf("%d", n))
}

func (g *guess) Auto() (string, error) {
	return g.Bot()
}

// ---- Blackjack ----

type blackjack struct {
	deck   []int
	player []int
	dealer []int
	pDone  bool
	over   bool
	won    bool
}

func newBlackjack() *blackjack {
	b := &blackjack{}
	b.deck = shuffledDeck()
	b.player = append(b.player, b.draw(), b.draw())
	b.dealer = append(b.dealer, b.draw())
	return b
}

func shuffledDeck() []int {
	d := make([]int, 52)
	for i := range d {
		d[i] = i%13 + 1
	}
	rand.Shuffle(len(d), func(i, j int) { d[i], d[j] = d[j], d[i] })
	return d
}

func (g *blackjack) draw() int {
	c := g.deck[0]
	g.deck = g.deck[1:]
	return c
}

func cardVal(c int) int {
	if c > 10 {
		return 10
	}
	return c
}

func handVal(h []int) int {
	total, aces := 0, 0
	for _, c := range h {
		if c == 1 {
			aces++
			total += 11
		} else {
			total += cardVal(c)
		}
	}
	for total > 21 && aces > 0 {
		total -= 10
		aces--
	}
	return total
}

func cardName(c int) string {
	names := []string{"A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"}
	return names[c-1]
}

func handNames(h []int) string {
	parts := make([]string, len(h))
	for i, c := range h {
		parts[i] = cardName(c)
	}
	return strings.Join(parts, " ")
}

func (g *blackjack) Name() string { return "blackjack" }
func (g *blackjack) Over() bool   { return g.over }

func (g *blackjack) State() map[string]any {
	dv := handVal(g.dealer)
	return map[string]any{
		"game":         g.Name(),
		"your_hand":    handNames(g.player),
		"your_total":   handVal(g.player),
		"dealer_hand":  handNames(g.dealer),
		"dealer_total": dv,
		"over":         g.over,
		"won":          g.won,
		"controls":     "hit or stand",
	}
}

func (g *blackjack) Move(action string) (string, error) {
	a := strings.ToLower(strings.TrimSpace(action))
	switch a {
	case "hit":
		g.player = append(g.player, g.draw())
		if handVal(g.player) > 21 {
			g.over = true
			return fmt.Sprintf("You busted (%d). I win.", handVal(g.player)), nil
		}
		return fmt.Sprintf("Your hand: %s = %d", handNames(g.player), handVal(g.player)), nil
	case "stand":
		g.pDone = true
		return g.finish(), nil
	default:
		return "", fmt.Errorf("send hit or stand")
	}
}

func (g *blackjack) finish() string {
	for handVal(g.dealer) < 17 {
		g.dealer = append(g.dealer, g.draw())
	}
	p, d := handVal(g.player), handVal(g.dealer)
	g.over = true
	msg := fmt.Sprintf("You %d, dealer %d. ", p, d)
	switch {
	case d > 21:
		msg += "Dealer busts, you win!"
		g.won = true
	case p > d:
		msg += "You win!"
		g.won = true
	case p == d:
		msg += "Push."
	default:
		msg += "I win."
	}
	return msg
}

func (g *blackjack) Bot() (string, error) {
	if handVal(g.player) < 17 {
		return g.Move("hit")
	}
	return g.Move("stand")
}

func (g *blackjack) Auto() (string, error) {
	return g.Bot()
}

// ---- Memory match ----
//
// A classic memory/concentration game. A human flips two cards per turn;
// the agent plays both sides by remembering every revealed card and matching
// pairs perfectly. Zero human interaction required.

const memoryCardCount = 16

type memory struct {
	cards    [memoryCardCount]string
	revealed [memoryCardCount]bool // face-up during the current turn
	matched  [memoryCardCount]bool
	seen     map[string][]int // value -> positions revealed so far
	current  []int            // cards face-up in the current turn
	flips    int
	over     bool
	done     bool
}

func newMemory() *memory {
	m := &memory{seen: map[string][]int{}}
	pairs := []string{"a", "b", "c", "d", "e", "f", "g", "h"}
	for i := 0; i < memoryCardCount; i++ {
		m.cards[i] = pairs[i/2]
	}
	rand.Shuffle(memoryCardCount, func(i, j int) { m.cards[i], m.cards[j] = m.cards[j], m.cards[i] })
	return m
}

func (m *memory) Name() string { return "memory" }
func (m *memory) Over() bool   { return m.over }

func (m *memory) State() map[string]any {
	return map[string]any{
		"game":    m.Name(),
		"flips":   m.flips,
		"matched": matchedCount(m.matched),
		"total":   memoryCardCount,
		"over":    m.over,
		"won":     m.over && m.done,
		"controls": "flip card 0-15",
	}
}

func matchedCount(matched [memoryCardCount]bool) int {
	n := 0
	for _, ok := range matched {
		if ok {
			n++
		}
	}
	return n
}

// pickNew returns the first card that is neither face-up, matched, nor already
// revealed in a previous turn (so the bot only flips fresh cards).
func (m *memory) pickNew() int {
	for i := 0; i < memoryCardCount; i++ {
		if !m.revealed[i] && !m.matched[i] && !m.wasSeen(i) {
			return i
		}
	}
	return -1
}

// wasSeen reports whether position i was revealed in an earlier turn.
func (m *memory) wasSeen(i int) bool {
	for _, x := range m.seen[m.cards[i]] {
		if x == i {
			return true
		}
	}
	return false
}

// seenIndex records a revealed position for its value (deduplicating).
func (m *memory) seenIndex(i int) {
	for _, x := range m.seen[m.cards[i]] {
		if x == i {
			return
		}
	}
	m.seen[m.cards[i]] = append(m.seen[m.cards[i]], i)
}

// knownPair returns a pair of positions whose values are already known.
func (m *memory) knownPair() (int, int, bool) {
	for _, idx := range m.seen {
		var pair []int
		for _, i := range idx {
			if !m.matched[i] {
				pair = append(pair, i)
			}
			if len(pair) == 2 {
				return pair[0], pair[1], true
			}
		}
	}
	return 0, 0, false
}

func (m *memory) Move(action string) (string, error) {
	var c int
	if _, err := fmt.Sscanf(action, "%d", &c); err != nil || c < 0 || c >= memoryCardCount {
		return "", fmt.Errorf("flip card 0-%d", memoryCardCount-1)
	}
	if m.over {
		return "game over", nil
	}
	if m.matched[c] {
		return "", fmt.Errorf("card %d already matched", c)
	}
	if len(m.current) == 2 {
		return "", fmt.Errorf("turn already complete, finish the pair first")
	}
	if containsInt(m.current, c) {
		return "", fmt.Errorf("card %d already flipped", c)
	}
	m.current = append(m.current, c)
	m.revealed[c] = true
	m.seenIndex(c)
	m.flips++
	if len(m.current) < 2 {
		return fmt.Sprintf("Flipped card %d: %q. Flip another.", c, m.cards[c]), nil
	}
	return m.resolve(), nil
}

func containsInt(list []int, n int) bool {
	for _, x := range list {
		if x == n {
			return true
		}
	}
	return false
}

// resolve settles the two face-up cards at the end of a turn.
func (m *memory) resolve() string {
	a, b := m.current[0], m.current[1]
	m.current = nil
	m.revealed[a] = false
	m.revealed[b] = false
	msg := fmt.Sprintf("Flipped %d and %d: %q vs %q. ", a, b, m.cards[a], m.cards[b])
	if m.cards[a] == m.cards[b] {
		m.matched[a] = true
		m.matched[b] = true
		msg += "Match!"
		if matchedCount(m.matched) == memoryCardCount {
			m.over = true
			m.done = true
			msg += fmt.Sprintf(" Board cleared in %d flips!", m.flips)
		}
	} else {
		msg += "No match."
	}
	return msg
}

// Bot plays the "human" side by flipping a known pair if it has one, else
// revealing a fresh card.
func (m *memory) Bot() (string, error) {
	if m.over {
		return "game over", nil
	}
	if len(m.current) == 0 {
		if a, b, ok := m.knownPair(); ok && !m.revealed[a] && !m.revealed[b] {
			m.current = append(m.current, a)
			m.revealed[a] = true
			m.flips++
			m.current = append(m.current, b)
			m.revealed[b] = true
			m.flips++
			return m.resolve(), nil
		}
	}
	c := m.pickNew()
	if c < 0 {
		return "no cards left", nil
	}
	return m.Move(fmt.Sprintf("%d", c))
}

func (m *memory) Auto() (string, error) {
	if m.over {
		return "game over", nil
	}
	return m.Bot()
}

// ---- Idle coin miner ----
//
// A cookie-clicker style idle game. The agent clicks to earn coins, spends
// them on upgrades (clicker + auto-mine), and keeps going until it reaches
// the goal. Fully autonomous: Auto() decides clicks and purchases.

type miner struct {
	coins     float64
	total     float64
	clickPwr  float64
	autoRate  float64
	upgrades  int
	goal      float64
	turn      int
	over      bool
}

func newMiner() *miner {
	return &miner{coins: 0, clickPwr: 1, autoRate: 0, goal: 1000}
}

func (m *miner) Name() string { return "idle-miner" }
func (m *miner) Over() bool   { return m.over }

func (m *miner) State() map[string]any {
	return map[string]any{
		"game":      m.Name(),
		"coins":     fmt.Sprintf("%.0f", m.coins),
		"click_pwr": fmt.Sprintf("%.1f", m.clickPwr),
		"auto_rate": fmt.Sprintf("%.1f", m.autoRate),
		"upgrades":  m.upgrades,
		"goal":      fmt.Sprintf("%.0f", m.goal),
		"over":      m.over,
		"won":       m.over && m.coins >= m.goal,
		"controls":  "click or buy (costs: clicker 20, auto 50, doubling 100)",
	}
}

func (m *miner) Move(action string) (string, error) {
	a := strings.ToLower(strings.TrimSpace(action))
	switch a {
	case "click":
		m.coins += m.clickPwr
		m.total += m.clickPwr
	case "buy", "buy clicker":
		if m.coins < 20 {
			return fmt.Sprintf("Not enough coins: %.0f/20", m.coins), nil
		}
		m.coins -= 20
		m.clickPwr++
		m.upgrades++
		m.autoRate += 0.5
	case "buy auto", "buy auto-mine":
		if m.coins < 50 {
			return fmt.Sprintf("Not enough coins: %.0f/50", m.coins), nil
		}
		m.coins -= 50
		m.autoRate += 2
		m.upgrades++
	case "buy double":
		if m.coins < 100 {
			return fmt.Sprintf("Not enough coins: %.0f/100", m.coins), nil
		}
		m.coins -= 100
		m.clickPwr *= 2
		m.upgrades++
	default:
		return "", fmt.Errorf("send click, buy clicker, buy auto-mine, or buy double")
	}
	m.tick()
	if m.coins >= m.goal {
		m.over = true
		return fmt.Sprintf("Goal reached! %.0f coins after %d turns. Mine complete.", m.coins, m.turn), nil
	}
	return fmt.Sprintf("Coins: %.0f (click %.1f, auto %.1f/turn, upgrades %d).", m.coins, m.clickPwr, m.autoRate, m.upgrades), nil
}

func (m *miner) tick() {
	m.turn++
	m.coins += m.autoRate
	m.total += m.autoRate
}

func (m *miner) Bot() (string, error) {
	return m.Auto()
}

// Auto plays a greedy strategy: always buy the cheapest affordable upgrade,
// otherwise click. The click power and auto-rate snowball quickly enough that
// the goal (1000) is always reached well before the 200-move cap.
func (m *miner) Auto() (string, error) {
	if m.over {
		return "game over", nil
	}
	if m.coins >= 20 {
		return m.Move("buy clicker")
	}
	return m.Move("click")
}
