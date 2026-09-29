import React from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

const base = "https://www.emriajewelry.com/";
const img = (name) => base + encodeURIComponent(name);

const products = [
  {name:"Kyma Necklace", cat:"Necklaces", image:"necklase.jpg"},
  {name:"Wave Choker", cat:"Necklaces", image:"necklase on woman.jpg"},
  {name:"Thalassa Set", cat:"Signature", image:"ring and necklace on woman.jpg"},
  {name:"Kyma Earrings", cat:"Earrings", image:"earrings main photo top phot.jpg"},
  {name:"Thalassa Ring", cat:"Rings", image:"ring1.jpg"},
  {name:"Night Rings", cat:"Rings", image:"2rings.jpg"},
  {name:"Tide Rings", cat:"Rings", image:"rings on flower.jpg"},
  {name:"Stacking Set", cat:"Rings", image:"rings on hand.jpg"},
  {name:"Driftwood Cuff", cat:"Bracelets", image:"bracelet on arm.jpg"},
  {name:"Shore Bracelet", cat:"Bracelets", image:"bracelet.jpg"},
];

function Header(){
  return <header className="header">
    <nav className="nav left">
      <a href="#shop">SHOP</a><a href="#story">ABOUT</a><a href="#search">SEARCH</a>
    </nav>
    <a className="brand" href="#">EMRIA</a>
    <nav className="nav right">
      <a href="#wishlist">WISHLIST</a><a href="#bag">BAG (0)</a>
    </nav>
  </header>
}

function Product({p}){
  return <article className="product">
    <div className="media"><img src={img(p.image)} alt={p.name}/></div>
    <div className="productInfo">
      <div><div className="productName">{p.name}</div><div className="productCat">{p.cat}</div></div>
      <button>VIEW PIECE</button>
    </div>
  </article>
}

function App(){
  return <div>
    <div className="announcement">HANDCRAFTED IN GREECE · STERLING SILVER · SMALL BATCHES</div>
    <Header/>

    <main>
      <section className="hero">
        <div className="heroMedia">
          <video autoPlay muted loop playsInline poster={img("ring and necklace on woman.jpg")}>
            <source src="/videos/hero.mp4" type="video/mp4"/>
          </video>
        </div>
        <div className="heroText">
          <p className="eyebrow">EMRIA / 925 SILVER</p>
          <h1>Jewelry with<br/>its own presence.</h1>
          <p className="copy">Sculptural silver pieces, formed by hand and designed to be worn every day.</p>
          <a className="lineLink" href="#shop">SHOP ALL <span>→</span></a>
          <p className="videoHint">Drop your own MP4 into <b>public/videos/hero.mp4</b> and this image becomes a looping video.</p>
        </div>
      </section>

      <section id="shop" className="shopIntro">
        <div>
          <p className="eyebrow">SHOP</p>
          <h2>Selected pieces</h2>
        </div>
        <div className="categories">
          <a>RINGS</a><a>NECKLACES</a><a>EARRINGS</a><a>BRACELETS</a>
        </div>
      </section>

      <section className="productGrid">
        {products.slice(0,8).map((p,i)=><Product key={i} p={p}/>)}
      </section>

      <section className="custom">
        <div className="customImage">
          <img src={img("rings on hand.jpg")} alt="EMRIA rings"/>
        </div>
        <div className="customText">
          <p className="eyebrow">PERSONAL / SMALL BATCHES</p>
          <h2>Made slowly.<br/>Made to feel yours.</h2>
          <p className="copy">A quieter section inspired by the custom-story rhythm of the reference site, but built around EMRIA’s own identity and imagery.</p>
          <a className="lineLink" href="#contact">CONTACT US <span>→</span></a>
        </div>
      </section>

      <section className="videoBand">
        <video autoPlay muted loop playsInline poster={img("earrings main photo top phot.jpg")}>
          <source src="/videos/detail.mp4" type="video/mp4"/>
        </video>
        <div className="videoOverlay"><span>MOVING IMAGE SLOT</span><b>DETAIL / MOTION / LIGHT</b></div>
      </section>

      <section className="productGrid second">
        {products.slice(8).map((p,i)=><Product key={i} p={p}/>)}
        <article className="editorialTile dark">
          <img src={img("logo sea asthetics.jpg")} alt="EMRIA"/>
          <div><p className="eyebrow">EMRIA</p><h3>Handcrafted in Greece.</h3></div>
        </article>
        <article className="editorialTile">
          <img src={img("necklase on woman.jpg")} alt="EMRIA necklace"/>
          <div><p className="eyebrow">THE FORM</p><h3>Distinctive, tactile, personal.</h3></div>
        </article>
      </section>

      <section id="story" className="story">
        <div className="storyBig">EMRIA</div>
        <div className="storyCopy">
          <p className="eyebrow">ABOUT</p>
          <h2>Silver as an object of expression.</h2>
          <p>Organic forms, irregular surfaces and pieces made in limited quantities. The jewelry stays at the center; the Aegean remains a quiet influence, not the main theme.</p>
        </div>
      </section>

      <section className="strip">
        {["ring1.jpg","rings on flower.jpg","ring and necklace on woman.jpg","bracelet on arm.jpg","earrings main photo top phot.jpg"].map((x,i)=>
          <img key={i} src={img(x)} alt="EMRIA detail"/>
        )}
      </section>
    </main>

    <footer id="contact">
      <div><b>CONTACT</b><a>Instagram</a><a>Email</a><span>Studio visits by appointment</span></div>
      <div><b>SHOP</b><a>Rings</a><a>Necklaces</a><a>Earrings</a><a>Bracelets</a></div>
      <div><b>INFORMATION</b><a>Delivery & Returns</a><a>Care Guide</a><a>Privacy</a></div>
      <div className="newsletter"><b>STAY CLOSE</b><span>Occasional notes from the studio.</span><label>Your e-mail <i>→</i></label></div>
    </footer>
    <div className="copyright">© EMRIA JEWELRY</div>
  </div>
}
createRoot(document.getElementById("root")).render(<App/>);
