import React from "react";import ReactDOM from "react-dom/client";import{Search,Heart,ShoppingBag,ArrowRight}from"lucide-react";import"./style.css";
const B="https://www.emriajewelry.com/";const I=n=>B+encodeURI(n);
const P=[
["ring1.jpg","THALASSA RING","RINGS","€89"],
["ring and necklace on woman.jpg","AEGEAN STORY","EDITORIAL","DISCOVER"],
["earrings.jpg","KYMA EARRINGS","EARRINGS","€74"],
["necklase.jpg","KYMA NECKLACE","NECKLACES","€96"],
["rings on hand.jpg","STACKING RINGS","RINGS","€82"],
["bracelet.jpg","SHORE BRACELET","BRACELETS","€78"]
];
function App(){return <div>
<header><nav><a href="#shop">SHOP</a><a href="#story">STORY</a><a href="#contact">CONTACT</a></nav><a className="logo">EMRIA</a><div className="tools"><Search size={17}/><span>WISHLIST</span><span>BAG (0)</span></div></header>
<section className="intro"><div><small>HANDCRAFTED IN GREECE</small><h1>Jewelry with<br/><i>its own presence.</i></h1></div><p>Distinctive jewelry made in small batches. Sculptural forms, refined details and pieces designed to feel personal.</p></section>
<section className="catalog" id="shop">{P.map((p,i)=><article className={(i===1||i===4)?"tile editorial":"tile"} key={p[1]}><div className="pic"><img src={I(p[0])}/>{i!==1&&<button><Heart size={17}/></button>}</div><div className="caption"><div><small>{p[2]}</small><b>{p[1]}</b></div><span>{p[3]}</span></div></article>)}</section>
<section className="story" id="story"><div className="storyPic"><img src={I("ring and necklace on woman.jpg")}/></div><div className="storyText"><small>02 / THE STORY</small><h2>Made slowly.<br/>Worn freely.</h2><p>EMRIA explores form, texture and individuality. Each piece is designed as a small object of expression — contemporary, tactile and easy to make your own.</p><a href="#shop">EXPLORE PIECES <ArrowRight size={15}/></a></div></section>
<section className="strip"><span>ORIGINAL FORMS</span><span>HANDCRAFTED IN GREECE</span><span>CONTEMPORARY JEWELRY</span><span>SMALL BATCH</span></section>
<footer id="contact"><div className="footerBrand">EMRIA</div><div className="footerGrid"><div><b>CONTACT</b><a href="https://www.instagram.com/emriajewelry/" target="_blank">Instagram</a><a href="mailto:hello@emriajewelry.com">Email</a><span>Studio visits by appointment</span></div><div><b>SHOP</b><a>Rings</a><a>Necklaces</a><a>Earrings</a><a>Bracelets</a></div><div><b>INFORMATION</b><a>Delivery & Returns</a><a>Care Guide</a><a>Privacy</a></div><div className="newsletter"><b>STAY CLOSE</b><p>Occasional notes from the studio.</p><div><input placeholder="Your e-mail"/><button><ArrowRight size={18}/></button></div></div></div><div className="bottom">© 2026 EMRIA JEWELRY <span>ATHENS · GREECE</span></div></footer>
</div>}ReactDOM.createRoot(document.getElementById("root")).render(<App/>);