"""Original, offline mini arcade engines; no ROMs, external images or network."""
import random

SHAPES=(((0,1),(1,1),(2,1),(3,1)),((0,0),(0,1),(1,1),(2,1)),((2,0),(0,1),(1,1),(2,1)),((1,0),(2,0),(1,1),(2,1)),((1,0),(2,0),(0,1),(1,1)),((1,0),(0,1),(1,1),(2,1)),((0,0),(1,0),(1,1),(2,1)))


class Blocks:
    def __init__(self,rng=None):
        self.rng=rng or random.Random();self.board=[[0]*10 for _ in range(20)];self.score=0;self.lines=0;self.over=False;self.bag=[];self.clock=0;self.spawn()
    @property
    def level(self):return self.lines//10+1
    def spawn(self):
        if not self.bag:self.bag=list(range(7));self.rng.shuffle(self.bag)
        self.kind=self.bag.pop();self.cells=SHAPES[self.kind];self.x=3;self.y=0
        if not self.fits(self.cells,self.x,self.y):self.over=True
    def fits(self,cells,x,y):return all(0<=x+dx<10 and 0<=y+dy<20 and not self.board[y+dy][x+dx] for dx,dy in cells)
    def move(self,dx,dy=0):
        if self.over:return False
        if self.fits(self.cells,self.x+dx,self.y+dy):self.x+=dx;self.y+=dy;return True
        if dy:self.lock()
        return False
    def rotate(self):
        if self.over or self.kind==3:return
        cells=tuple((2-y,x) for x,y in self.cells)
        for kick in (0,-1,1,-2,2):
            if self.fits(cells,self.x+kick,self.y):self.cells=cells;self.x+=kick;break
    def drop(self):
        if self.over:return
        while self.fits(self.cells,self.x,self.y+1):self.y+=1;self.score+=2
        self.lock()
    def lock(self):
        for dx,dy in self.cells:self.board[self.y+dy][self.x+dx]=self.kind+1
        remaining=[row for row in self.board if not all(row)];cleared=20-len(remaining)
        self.board=[[0]*10 for _ in range(cleared)]+remaining
        self.score+=(0,100,300,500,800)[cleared]*self.level;self.lines+=cleared;self.clock=0;self.spawn()
    def tick(self,seconds):
        if self.over:return
        self.clock+=seconds
        if self.clock>=max(.09,.65-.045*(self.level-1)):self.clock=0;self.move(0,1)


class Gomoku:
    def __init__(self,rng=None):
        self.rng=rng or random.Random();self.board=[[0]*15 for _ in range(15)];self.score=0;self.over=False;self.winner=0;self.turns=0;self.last=None
    def won(self,x,y,side):
        for dx,dy in ((1,0),(0,1),(1,1),(1,-1)):
            count=1
            for sign in (-1,1):
                for length in range(1,5):
                    a,b=x+dx*length*sign,y+dy*length*sign
                    if not(0<=a<15 and 0<=b<15) or self.board[b][a]!=side:break
                    count+=1
            if count>=5:return True
        return False
    def place(self,x,y,side):
        if self.over or not(0<=x<15 and 0<=y<15) or self.board[y][x]:return False
        self.board[y][x]=side;self.last=(x,y);self.turns+=1
        if self.won(x,y,side):self.over=True;self.winner=side;self.score=(1000+max(0,225-self.turns)*5) if side==1 else 0
        elif self.turns==225:self.over=True;self.score=100
        return True
    def candidates(self):
        used=[(x,y) for y in range(15) for x in range(15) if self.board[y][x]]
        if not used:return [(7,7)]
        return sorted({(x+dx,y+dy) for x,y in used for dx in range(-2,3) for dy in range(-2,3) if 0<=x+dx<15 and 0<=y+dy<15 and not self.board[y+dy][x+dx]})
    def ai(self):
        candidates=self.candidates()
        for side in (2,1):
            for x,y in candidates:
                self.board[y][x]=side;win=self.won(x,y,side);self.board[y][x]=0
                if win:self.place(x,y,2);return
        def rank(point):
            x,y=point;score=14-abs(7-x)-abs(7-y)
            for side in (1,2):
                for dx,dy in ((1,0),(0,1),(1,1),(1,-1)):
                    count=0;opened=0
                    for sign in (-1,1):
                        for length in range(1,5):
                            a,b=x+dx*length*sign,y+dy*length*sign
                            if not(0<=a<15 and 0<=b<15):break
                            if self.board[b][a]==side:count+=1
                            else:
                                opened+=self.board[b][a]==0;break
                    score+=(8**count)*(opened+1)*(1.05 if side==2 else 1)
            return score
        if candidates:self.place(*max(candidates,key=rank),2)
    def human(self,x,y):
        if self.place(x,y,1) and not self.over:self.ai()
    def tick(self,seconds):pass


class Shooter:
    def __init__(self,rng=None):
        self.rng=rng or random.Random();self.score=0;self.over=False;self.x=250.;self.lives=3;self.wave=0;self.bullets=[];self.enemy_bullets=[];self.direction=1;self.clock=0;self.cooldown=0;self.invincible=0;self.left=False;self.right=False;self.fire=False;self.next_wave()
    def next_wave(self):
        self.wave+=1;self.enemies=[[60.+column*54,55.+row*38] for row in range(4) for column in range(8)];self.enemy_bullets=[]
    def tick(self,seconds):
        if self.over:return
        self.x=max(16,min(484,self.x+(int(self.right)-int(self.left))*270*seconds))
        self.cooldown=max(0,self.cooldown-seconds);self.invincible=max(0,self.invincible-seconds);self.clock+=seconds
        if self.fire and self.cooldown<=0:self.bullets.append([self.x,548.]);self.cooldown=.18
        if any(enemy[0]<18 or enemy[0]>482 for enemy in self.enemies):
            self.direction*=-1
            for enemy in self.enemies:enemy[1]+=15;enemy[0]=max(18,min(482,enemy[0]))
        for enemy in self.enemies:enemy[0]+=self.direction*(23+self.wave*5)*seconds
        for bullet in self.bullets:bullet[1]-=480*seconds
        for bullet in self.enemy_bullets:bullet[1]+=(150+self.wave*12)*seconds
        for bullet in list(self.bullets):
            target=next((enemy for enemy in self.enemies if abs(enemy[0]-bullet[0])<18 and abs(enemy[1]-bullet[1])<15),None)
            if target is not None:self.enemies.remove(target);self.bullets.remove(bullet);self.score+=100
        if self.clock>=max(.2,.85-self.wave*.04) and self.enemies:
            self.clock=0;enemy=self.rng.choice(self.enemies);self.enemy_bullets.append([enemy[0],enemy[1]+14])
        if self.invincible<=0 and any(abs(bullet[0]-self.x)<16 and abs(bullet[1]-560)<20 for bullet in self.enemy_bullets):
            self.lives-=1;self.invincible=1.4;self.enemy_bullets=[]
        self.bullets=[bullet for bullet in self.bullets if bullet[1]>0];self.enemy_bullets=[bullet for bullet in self.enemy_bullets if bullet[1]<610]
        if self.lives<=0 or any(enemy[1]>535 for enemy in self.enemies):self.over=True
        elif not self.enemies:self.score+=500;self.next_wave()


def platform_step(x,y,vy,speed,dt,platforms,width=500):
    x=max(12,min(width-38,x+speed*dt));bottom=y+34;vy=min(650,vy+950*dt);y+=vy*dt;ground=False
    for px,py,pw in platforms:
        if vy>=0 and bottom<=py+1 and y+34>=py and x+26>px and x<px+pw:y=py-34;vy=0;ground=True
    return x,y,vy,ground


class Jumper:
    """Original three-stage side-scroller; no licensed characters or assets."""
    def __init__(self,rng=None):
        self.rng=rng or random.Random();self.score=0;self.over=False;self.won=False;self.lives=3;self.stage=0;self.left=False;self.right=False;self.jump=False;self.invincible=0;self.next_stage()
    def next_stage(self):
        self.stage+=1;self.x=45.;self.y=500.;self.vy=0.;self.grounded=False;self.camera=0
        self.platforms=[(0,580,510),(610,580,430),(1140,580,420),(1660,580,940),(230,455,140),(470,365,150),(820,440,150),(1260,420,170),(1550,335,160),(1910,450,180),(2210,355,170)]
        self.coins=[(x,545) for x in range(160,2520,120) if not (510<x<610 or 1040<x<1140 or 1560<x<1660)]+[(x+40,y-28) for x,y,_ in self.platforms[4:]]
        self.enemies=[[760.,546.,1,630,1000],[1350.,546.,-1,1160,1520],[1850.,546.,1,1680,2560],[2350.,546.,-1,1680,2560]]
    def hurt(self):
        if self.invincible>0:return
        self.lives-=1;self.invincible=2.;self.x=45.;self.y=500.;self.vy=0
        if self.lives<=0:self.over=True
    def tick(self,dt):
        if self.over:return
        self.invincible=max(0,self.invincible-dt)
        if self.jump and self.grounded:self.vy=-540
        self.jump=False;bottom=self.y+34
        self.x,self.y,self.vy,self.grounded=platform_step(self.x,self.y,self.vy,(int(self.right)-int(self.left))*210,dt,self.platforms,2600);self.camera=max(0,min(2100,self.x-180))
        for coin in list(self.coins):
            if abs(coin[0]-self.x-13)<23 and abs(coin[1]-self.y-17)<28:self.coins.remove(coin);self.score+=100
        for enemy in list(self.enemies):
            enemy[0]+=enemy[2]*(45+self.stage*12)*dt
            if enemy[0]<enemy[3] or enemy[0]>enemy[4]:enemy[0]=max(enemy[3],min(enemy[4],enemy[0]));enemy[2]*=-1
            if abs(enemy[0]-self.x)<27 and abs(enemy[1]-self.y)<30:
                if self.vy>0 and bottom<enemy[1]+12:self.enemies.remove(enemy);self.vy=-280;self.score+=250
                else:self.hurt()
        if self.y>650:self.hurt()
        if self.x>2535:
            self.score+=2000+self.lives*250
            if self.stage>=3:self.over=True;self.won=True
            else:self.next_stage()


class Bubbles:
    """Original bubble-capture platform arena with five stages."""
    def __init__(self,rng=None):
        self.rng=rng or random.Random();self.score=0;self.over=False;self.won=False;self.lives=3;self.stage=0;self.left=False;self.right=False;self.jump=False;self.fire=False;self.direction=1;self.invincible=0;self.cooldown=0
        self.platforms=[(0,580,500),(35,450,170),(290,450,175),(170,330,170),(35,215,130),(340,215,125)];self.next_stage()
    def next_stage(self):
        self.stage+=1;self.x=40.;self.y=530.;self.vy=0.;self.grounded=False;self.orbs=[]
        self.enemies=[dict(x=250.+i*35,y=530.,vy=0.,direction=(-1 if i%2 else 1),grounded=False) for i in range(min(6,self.stage+2))]
    def tick(self,dt):
        if self.over:return
        self.cooldown=max(0,self.cooldown-dt);self.invincible=max(0,self.invincible-dt)
        if self.left!=self.right:self.direction=-1 if self.left else 1
        if self.jump and self.grounded:self.vy=-540
        self.jump=False;self.x,self.y,self.vy,self.grounded=platform_step(self.x,self.y,self.vy,(int(self.right)-int(self.left))*190,dt,self.platforms)
        if self.fire and self.cooldown<=0:self.orbs.append(dict(x=self.x+13+self.direction*22,y=self.y+13,age=0.,direction=self.direction,captured=False));self.cooldown=.3
        for enemy in self.enemies:
            if enemy['grounded'] and self.rng.random()<dt*.7:enemy['vy']=-370
            enemy['x'],enemy['y'],enemy['vy'],enemy['grounded']=platform_step(enemy['x'],enemy['y'],enemy['vy'],enemy['direction']*(55+self.stage*8),dt,self.platforms)
            if enemy['x']<=12 or enemy['x']>=462:enemy['direction']*=-1
            if not self.invincible and abs(enemy['x']-self.x)<25 and abs(enemy['y']-self.y)<30:self.lives-=1;self.invincible=2.;self.x=40.;self.y=530.;self.vy=0.
        for orb in list(self.orbs):
            orb['age']+=dt
            if orb['age']<.75:orb['x']+=orb['direction']*180*dt
            else:orb['y']-=65*dt
            orb['x']=max(16,min(484,orb['x']))
            if not orb['captured']:
                target=next((e for e in self.enemies if abs(e['x']+13-orb['x'])<25 and abs(e['y']+17-orb['y'])<25),None)
                if target is not None:self.enemies.remove(target);orb['captured']=True;orb['age']=.8;self.score+=50
            elif abs(self.x+13-orb['x'])<35 and abs(self.y+17-orb['y'])<35:self.orbs.remove(orb);self.score+=300;continue
            if orb['y']<20 or orb['age']>9:
                self.orbs.remove(orb)
                if orb['captured']:self.enemies.append(dict(x=orb['x']-13,y=30.,vy=0.,direction=self.rng.choice((-1,1)),grounded=False))
        if self.lives<=0:self.over=True
        elif not self.enemies and not any(orb['captured'] for orb in self.orbs):
            self.score+=1000
            if self.stage>=5:self.won=True;self.over=True
            else:self.next_stage()


class Raccoon:
    """Original fruit-and-ladders arcade, with no original-game assets/code."""
    def __init__(self,rng=None):
        self.rng=rng or random.Random();self.score=0;self.over=False;self.won=False;self.lives=3;self.stage=0
        self.left=False;self.right=False;self.up=False;self.down=False;self.jump=False;self.invincible=0
        self.platforms=[(0,y,500) for y in (580,440,300,160)]
        self.ladders=[(70,440,580),(430,300,440),(250,160,300)];self.next_stage()
    def respawn(self):
        self.x=25.;self.y=546.;self.vy=0.;self.grounded=True;self.climbing=False
    def next_stage(self):
        self.stage+=1;self.time_left=95.;self.respawn()
        self.fruits=[(float(x),float(y-22)) for _,y,_ in self.platforms for x in (115,205,330,445)]
        self.enemies=[dict(x=float(290 if i%2 else 365),y=float(y-30),direction=1 if i%2 else -1) for i,(_,y,_) in enumerate(self.platforms)]
    def hurt(self):
        if self.invincible>0:return
        self.lives-=1;self.invincible=2.;self.respawn();self.time_left=max(35.,self.time_left)
        if self.lives<=0:self.over=True
    def tick(self,dt):
        if self.over:return
        dt=max(0,min(.05,dt));self.invincible=max(0,self.invincible-dt);self.time_left-=dt
        if self.time_left<=0:self.hurt();return
        ladder=next(((x,top,bottom) for x,top,bottom in self.ladders if abs(self.x+13-x)<22 and top-2<=self.y+34<=bottom+2),None)
        vertical=int(self.down)-int(self.up)
        if vertical and ladder:
            x,top,bottom=ladder;self.climbing=True;self.x=x-13;self.vy=0
            self.y=max(top-34,min(bottom-34,self.y+vertical*135*dt));self.grounded=False
            if self.y in (top-34,bottom-34):self.climbing=False;self.grounded=True
        else:
            if self.left or self.right or self.jump:self.climbing=False
            if not self.climbing:
                if self.jump and self.grounded:self.vy=-390
                self.x,self.y,self.vy,self.grounded=platform_step(self.x,self.y,self.vy,(int(self.right)-int(self.left))*185,dt,self.platforms)
        self.jump=False
        for fruit in list(self.fruits):
            if abs(fruit[0]-self.x-13)<24 and abs(fruit[1]-self.y-17)<27:self.fruits.remove(fruit);self.score+=100
        for enemy in self.enemies:
            enemy['x']+=enemy['direction']*(48+self.stage*9)*dt
            if enemy['x']<12 or enemy['x']>460:enemy['x']=max(12,min(460,enemy['x']));enemy['direction']*=-1
            if abs(enemy['x']-self.x)<23 and abs(enemy['y']-self.y)<26:self.hurt()
        if not self.over and not self.fruits:
            self.score+=1000+int(max(0,self.time_left))*10
            if self.stage>=5:self.over=True;self.won=True
            else:self.next_stage()
