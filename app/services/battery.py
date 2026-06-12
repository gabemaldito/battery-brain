def decide_action(energy_price, average_radiation):
  
    if energy_price < 50 and average_radiation > 400:
       return "CHARGE" 
    elif energy_price > 150: 
        return "DISCHARGE"
    else:
        return "HOLD"
        
    