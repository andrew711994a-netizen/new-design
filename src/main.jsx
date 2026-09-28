import React,{useState} from "react";
import ReactDOM from "react-dom/client";
import {Menu,X,Search,ShoppingBag,Heart,ArrowUpRight} from "lucide-react";
import "./style.css";

const BASE="https://www.emriajewelry.com/";
const enc=(s)=>BASE+encodeURI(s);
const products=[
 {name:"Kyma Necklace",cat:"Necklaces",detail:"Sterling silver · Wave · Adjustable",img:"necklase.jpg"},
 {name:"Thalassa Ring",cat:"Rings",detail:"Sterling silver · Open band",img:"ring1.jpg"},
 {name:"Night Rings",cat:"Rings",detail:"Oxidised silver · Set of 2",img:"2rings.jpg"},
 {name:"Aegean Ring",cat:"Rings",detail:"Sterling silver · By the sea",img:"ring summer.jpg"},
 {name:"Stacking Set",cat:"Rings",detail:"Sterling silver · Mix & match",img:"rings on hand.jpg"},
 {name:"Driftwood Cuff",cat:"Bracelets",detail:"Sterling silver · Open cuff",img:"bracelet on arm.jpg"},
 {name:"Shore Bracelet",cat:"Bracelets",detail:"Sterling silver · Adjustable",img:"bracelet.jpg"},
 {name:"Kyma Earrings",cat:"Earrings",detail:"Sterling silver · Drop",img:"earrings.jpg"}
];

function App(){
 const [menu,setMenu]=useState(false),[filter,setFilter]=useState("All");
 const shown=filter==="All"?products:products.filter(p=>p.cat===filter);
 return <div>
  <header className="header">
   <button className="mobile icon" onClick={()=>setMenu(true)}><Menu/></button>
   <nav className="nav left"><a href="#shop">SHOP</a><a href="#about">ABOUT</a></nav>
   <a className="logo" href="#">EMRIA</a>
   <nav className="nav right"><a href="https://www.instagram.com/emriajewelry/" target="_blank">INSTAGRAM</a><Search size={18}/><Heart size={18}/><span className="cart">CART (0)</span></nav>
  </header>
  {menu&&<div className="drawer"><button className="close icon" onClick={()=>setMenu(false)}><X/></button><a href="#shop" onClick={()=>setMenu(false)}>Shop</a><a href="#about" onClick={()=>setMenu(false)}>About</a><a href="https://www.instagram.com/emriajewelry/">Instagram</a></div>}

  <section className="hero">
   <img src={enc("logo sea asthetics.jpg")} alt="Emria Jewelry in the sea"/>
   <div className="heroShade"></div>
   <div className="heroCopy"><p>HANDCRAFTED IN GREECE</p><h1>Objects shaped<br/>by the sea.</h1><a href="#shop">DISCOVER THE COLLECTION <ArrowUpRight size={15}/></a></div>
  </section>

  <div className="marquee"><span>STERLING SILVER</span><span>HANDCRAFTED IN GREECE</span><span>MEDITERRANEAN FORMS</span><span>LIMITED PIECES</span></div>

  <section className="statement" id="about">
   <div className="index">01</div>
   <div><p className="kicker">EMRIA / ATHENS</p><h2>Jewelry made slowly,<br/><i>worn instinctively.</i></h2></div>
   <p className="body">Organic silver forms inspired by the Aegean: light on water, salt on skin, shapes softened by time. Each piece carries the marks of the hand that formed it.</p>
  </section>

  <section className="editorial">
   <div className="editorialImage"><img src={enc("ring and necklace on woman.jpg")} alt="Emria jewelry worn"/></div>
   <div className="editorialCopy"><span>THE EVERYDAY OBJECT</span><h2>Made to move<br/>with you.</h2><p>Unpolished perfection. Silver that changes with wear and becomes more personal over time.</p><a href="#shop">SHOP ALL <ArrowUpRight size={14}/></a></div>
  </section>

  <section className="shop" id="shop">
   <div className="shopTop"><div><p className="kicker">SHOP</p><h2>All pieces</h2></div><div className="filters">{["All","Necklaces","Earrings","Rings","Bracelets"].map(x=><button className={filter===x?"active":""} onClick={()=>setFilter(x)} key={x}>{x}</button>)}</div></div>
   <div className="grid">{shown.map((p,i)=><article className="card" key={p.name}>
    <div className="photo"><img src={enc(p.img)} alt={p.name}/><button className="wish"><Heart size={18}/></button><span className="num">{String(i+1).padStart(2,"0")}</span></div>
    <div className="meta"><div><span>{p.cat}</span><h3>{p.name}</h3><p>{p.detail}</p></div><ArrowUpRight size={18}/></div>
   </article>)}</div>
  </section>

  <section className="banner"><img src={enc("necklase.jpg")} alt="Emria necklace"/><div><p>HANDCRAFTED WITH INTENTION</p><h2>Silver, water,<br/>movement.</h2></div></section>

  <section className="philosophy">
   <p className="kicker">PHILOSOPHY</p><h2>Nothing perfectly still.<br/>Nothing exactly the same.</h2>
   <p>We believe the small irregularities are what make an object alive. EMRIA pieces are made to be touched, worn, marked and kept.</p>
  </section>

  <section className="insta">
   <div className="instaHead"><h2>Follow the journey</h2><a href="https://www.instagram.com/emriajewelry/" target="_blank">@EMRIAJEWELRY <ArrowUpRight size={14}/></a></div>
   <div className="instaGrid">{["rings on hand.jpg","bracelet on arm.jpg","earrings.jpg","ring summer.jpg"].map(x=><img key={x} src={enc(x)} alt="Emria jewelry"/>)}</div>
  </section>

  <footer><div className="footerLogo">EMRIA</div><div className="footcols"><div><b>NAVIGATE</b><a href="#shop">Shop</a><a href="#about">About</a></div><div><b>CONTACT</b><a href="https://www.instagram.com/emriajewelry/" target="_blank">Instagram</a><a href="mailto:hello@emriajewelry.com">Email</a></div><div><b>ORIGIN</b><span>Handcrafted in Greece</span><span>Inspired by the Aegean</span></div></div><div className="copyright">© 2026 EMRIA JEWELRY</div></footer>
 </div>
}
ReactDOM.createRoot(document.getElementById("root")).render(<App/>);